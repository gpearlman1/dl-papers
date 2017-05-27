import tensorflow as tf
from tensorflow.contrib.distributions import Uniform
from tensorflow.contrib import slim
from activations import lrelu
from distributions import normal_for_given_uniform_size


class InfoGAN(object):
    def __init__(
            self, z_size, c_sizes, c_distributions, reg_rate,
            image_size, channel_size, q_hidden_size,
            g_filter_number, d_filter_number,
            g_filter_size, d_filter_size,):
        # model-wise initializer
        self._initialzier = tf.truncated_normal_initializer(stddev=0.002)

        # basic hyperparameters
        self.z_size = z_size
        self.c_sizes = c_sizes
        self.c_distributions = c_distributions
        self.reg_rate = reg_rate
        self.image_size = image_size
        self.channel_size = channel_size
        self.q_hidden_size = q_hidden_size
        self.g_filter_number = g_filter_number
        self.d_filter_number = d_filter_number
        self.g_filter_size = g_filter_size
        self.d_filter_size = d_filter_size

        # basic placeholders
        self.z_in = tf.placeholder(
            shape=[None, z_size], dtype=tf.float32
        )
        self.c_in = tf.placeholder(
            shape=[None, sum(c_sizes)], dtype=tf.float32
        )
        self.image_in = tf.placeholder(
            shape=[None, image_size, image_size, channel_size],
            dtype=tf.float32,
        )

        # build graph using a generator and a discriminator.
        self.G = self.generator(self.z_in, self.c_in)
        self.D_x, self.D_x_logits = self.discriminator(self.image_in)
        self.D_g, self.D_g_logits = self.discriminator(self.G, reuse=True)
        self.encoded_G = self.discriminator(self.G, reuse=True, encode=True)
        self.c_given_G = self.estimate_posterior_latent_code(self.encoded_g)
        self.estimated_mutual_information = self.estimate_mutual_information(
            self.c_in, self.c_given_G
        )

        # build objective functions
        self.d_loss_real = self._sigmoid_cross_entropy_loss(
            logits=self.D_x_logits, labels=tf.ones_like(self.D_x)
        )
        self.d_loss_fake = self._sigmoid_cross_entropy_loss(
            logits=self.D_g_logits, labels=tf.zeros_like(self.D_g)
        )
        self.d_loss = self.d_loss_real + self.d_loss_fake
        self.g_loss = self._sigmoid_cross_entropy_loss(
            logits=self.D_g_logits, labels=tf.ones_like(self.D_g)
        )
        # regularize objectives to maximize mutual information between
        # original code and reconstructed latent code.
        self.d_loss -= self.estimated_mutual_information
        self.g_loss -= self.estimated_mutual_information

        # variables
        self.g_vars = [v for v in tf.trainable_variables() if 'g_' in v.name]
        self.d_vars = [v for v in tf.trainable_variables() if 'd_' in v.name]
        self.q_vars = [v for v in tf.trainable_variables() if 'q_' in v.name]

    def generator(self, z, c):
        # project zc
        zc = tf.concat([z, c], axis=1)
        zc_filter_number = self.g_filter_number * 8
        zc_projection_size = self.image_size // 8
        zc_projected = slim.fully_connected(
            zc,
            zc_projection_size * zc_projection_size * zc_filter_number,
            activation_fn=tf.nn.relu,
            normalizer_fn=slim.batch_norm,
            weights_initializer=self._initialzier,
            scope='g_projection',
        )
        zc_reshaped = tf.reshape(
            zc_projected,
            [-1, zc_projection_size, zc_projection_size, zc_filter_number]
        )

        # transposed conv1
        g_conv1_filter_number = zc_filter_number // 2
        g_conv1 = slim.convolution2d_transpose(
            zc_reshaped,
            num_outputs=g_conv1_filter_number,
            kernel_size=[self.g_filter_size, self.g_filter_size],
            stride=[2, 2],
            padding='SAME',
            activation_fn=tf.nn.relu,
            normalizer_fn=slim.batch_norm,
            weights_initializer=self._initialzier,
            scope='g_conv1',
        )

        # transposed conv2
        g_conv2_filter_number = g_conv1_filter_number // 2
        g_conv2 = slim.convolution2d_transpose(
            g_conv1,
            num_outputs=g_conv2_filter_number,
            kernel_size=[self.g_filter_size, self.g_filter_size],
            stride=[2, 2],
            padding='SAME',
            activation_fn=tf.nn.relu,
            normalizer_fn=slim.batch_norm,
            weights_initializer=self._initialzier,
            scope='g_conv2',
        )

        # transposed conv3
        g_conv3_filter_number = g_conv2_filter_number // 2
        g_conv3 = slim.convolution2d_transpose(
            g_conv2,
            num_outputs=g_conv3_filter_number,
            kernel_size=[self.g_filter_size, self.g_filter_size],
            stride=[2, 2],
            padding='SAME',
            activation_fn=tf.nn.relu,
            normalizer_fn=slim.batch_norm,
            weights_initializer=self._initialzier,
            scope='g_conv3',
        )

        # out
        g_out = slim.convolution2d_transpose(
            g_conv3,
            num_outputs=self.channel_size,
            kernel_size=[self.image_size, self.image_size], padding='SAME',
            biases_initializer=None,
            activation_fn=tf.nn.tanh,
            weights_initializer=self._initialzier,
            scope='g_out'
        )

        return g_out

    def discriminator(self, bottom, reuse=False, encode=False):
        d_conv1_filter_number = self.d_filter_number
        d_conv1 = slim.convolution2d(
            bottom,
            d_conv1_filter_number,
            kernel_size=[self.d_filter_size, self.d_filter_size],
            stride=[2, 2], padding='SAME',
            activation_fn=lrelu,
            normalizer_fn=slim.batch_norm,
            biases_initializer=None,
            weights_initializer=self._initialzier,
            reuse=reuse, scope='d_conv1'
        )

        d_conv2_filter_number = d_conv1_filter_number * 2
        d_conv2 = slim.convolution2d(
            d_conv1,
            d_conv2_filter_number,
            kernel_size=[self.d_filter_size, self.d_filter_size],
            stride=[2, 2],
            padding='SAME',
            activation_fn=lrelu,
            normalizer_fn=slim.batch_norm,
            biases_initializer=None,
            weights_initializer=self._initialzier,
            reuse=reuse, scope='d_conv2'
        )

        d_conv3_filter_number = d_conv2_filter_number * 2
        d_conv3 = slim.convolution2d(
            d_conv2,
            d_conv3_filter_number,
            kernel_size=[self.d_filter_size, self.d_filter_size],
            stride=[2, 2],
            padding='SAME',
            activation_fn=lrelu,
            normalizer_fn=slim.batch_norm,
            biases_initializer=None,
            weights_initializer=self._initialzier,
            reuse=reuse, scope='d_conv3'
        )

        d_out = slim.fully_connected(
            slim.flatten(d_conv3), 1,
            weights_initializer=self._initialzier,
            reuse=reuse,
            scope='d_out'
        )

        # return the encoded features or the discriminator's judgement.
        if encode:
            return d_conv3
        else:
            return tf.nn.sigmoid(d_out), d_out

    def estimate_posterior_latent_code(self, encoded_g, reuse=False):
        projected = slim.fully_connected(
            encoded_g, self.q_hidden_size,
            weights_initializer=self._initialzier,
            activation_fn=lrelu,
            normalizer_fn=slim.batch_norm,
            reuse=reuse, scope='q_projection'
        )

        latent_code_approximated = slim.fully_connected(
            projected, sum(self.c_sizes),
            weights_initializer=self._initialzier,
            reuse=reuse, scope='q_out'
        )

        return latent_code_approximated

    def estimate_mutual_information(self, c, cg):
        # Use normal distribution for calculating log likelihood of latent
        # code from the uniform distributions. This is to avoid 0 likelihoods
        # from the uniform distributions.
        c_log_likelihoods = [
            normal_for_given_uniform_size(d).log_prob(c_)
            if isinstance(d, Uniform) else d.log_prob(c_)
            for d, c_ in zip(self.c_distributions, c)
        ]
        cg_log_likelihoods = [
            normal_for_given_uniform_size(d).log_prob(cg_)
            if isinstance(d, Uniform) else d.log_prob(cg_)
            for d, cg_ in zip(self.c_distributions, cg)
        ]

        # Estimate entropies of latent code and posterior latent code.
        estimated_c_entropy = tf.reduce_mean(-c_log_likelihoods)
        estimated_cg_entropy = tf.reduce_mean(-cg_log_likelihoods)

        # Return estimated mutual information between latent code and posterior
        # latent code.
        return estimated_c_entropy - estimated_cg_entropy

    @staticmethod
    def _sigmoid_cross_entropy_loss(logits, labels):
        return tf.reduce_mean(tf.sigmoid_cross_entropy_with_logits(
                logits=logits, labels=labels
        ))
