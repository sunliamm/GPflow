import gpflow
import unittest
import tensorflow as tf

import numpy as np
from numpy.testing import assert_almost_equal, assert_allclose

from nose.plugins.attrib import attr
from gpflow.test_util import GPflowTestCase

@attr(speed='slow')
class SampleGaussianTest(GPflowTestCase):
    class Gauss(gpflow.models.Model):
        def __init__(self, **kwargs):
            super(SampleGaussianTest.Gauss, self).__init__(**kwargs)
            self.x = gpflow.Param(np.zeros(3))
        @gpflow.params_as_tensors
        def build_objective(self):
            return 0.5 * tf.reduce_sum(tf.square(self.x))
        def _build_likelihood(self):
            return tf.constant(0.0, dtype=gpflow.settings.np_float)

    def setUp(self):
        tf.set_random_seed(1)
        self.m = SampleGaussianTest.Gauss()
        self.hmc = gpflow.train.HMC()

    def test_mean_cov(self):
        with self.test_context():
            self.m.compile()
            num_samples = 1000
            samples = self.hmc.sample(self.m, num_samples=num_samples,
                                      lmin=10, lmax=21, epsilon=0.05)
            self.assertEqual(samples.shape, (num_samples, 2))
            xs = np.array(samples[self.m.x.full_name].tolist(), dtype=np.float32)
            mean = xs.mean(0)
            cov = np.cov(xs.T)
            # TODO(@awav): inspite of the fact that we set up graph's random seed,
            # the operation seed is still assigned by tensorflow automatically
            # and hence sample output numbers are not deterministic.
            self.assertTrue(np.sum(np.abs(mean) < 0.1) >= mean.size/2)
            cov_standard = np.eye(cov.shape[0])
            # assert_allclose(cov, cov_standard, rtol=1e-1, atol=1e-1)

    def test_rng(self):
        """
        Make sure all randomness can be atributed to the rng
        """
        def get_samples():
            num_samples = 100
            m = SampleGaussianTest.Gauss()
            m.compile()
            hmc = gpflow.train.HMC()
            samples = hmc.sample(m, num_samples=num_samples, epsilon=0.05,
                                 lmin=10, lmax=21, thin=10)
            return np.array(samples[m.x.full_name].values.tolist(), dtype=np.float32)

        with self.test_context():
            tf.set_random_seed(1)
            s1 = get_samples()

        with self.test_context():
            tf.set_random_seed(2)
            s2 = get_samples()

        with self.test_context():
            tf.set_random_seed(3)
            s3 = get_samples()

        self.assertFalse(np.all(s1 == s2))
        self.assertFalse(np.all(s1 == s3))

    def test_burn(self):
        with self.test_context():
            self.m.compile()
            num_samples = 10
            x0 = self.m.read_trainables()[0]
            samples = self.hmc.sample(self.m, num_samples=num_samples,
                                      lmin=10, lmax=21, epsilon=0.05,
                                      burn=10)

            x = samples.drop('logprobs', axis=1).iloc[-1][0]
            self.assertEqual(samples.shape, (10, 2))
            self.assertEqual(x.shape, (3,))
            self.assertFalse(np.all(x == x0))

    def test_columns_names(self):
        with self.test_session():
            self.m.compile()
            num_samples = 10
            samples = self.hmc.sample(self.m, num_samples=num_samples,
                                      lmin=10, lmax=21, epsilon=0.05)
            names = [p.full_name for p in self.m.parameters]
            names.append('logprobs')
            names = set(names)
            col_names = set(samples.columns)
            self.assertEqual(col_names, names)


class SampleModelTest(GPflowTestCase):
    """
    Create a very simple model and make sure samples form is make sense.
    """
    def setUp(self):
        tf.set_random_seed(1)
        rng = np.random.RandomState(0)
        class Quadratic(gpflow.models.Model):
            def __init__(self):
                super(Quadratic, self).__init__()
                self.x = gpflow.Param(rng.randn(2), dtype=gpflow.settings.np_float)
            @gpflow.params_as_tensors
            def _build_likelihood(self):
                return -tf.reduce_sum(tf.square(self.x))
        self.m = Quadratic()

        def get_samples():
            num_samples = 100
            m = SampleGaussianTest.Gauss()
            m.compile()
            hmc = gpflow.train.HMC()
            samples = hmc.sample(m, num_samples=num_samples, epsilon=0.05,
                                 lmin=10, lmax=20, thin=10)
            return np.array(samples[m.x.full_name].values.tolist(), dtype=np.float32)

    def test_mean(self):
        with self.test_context():
            self.m.compile()
            hmc = gpflow.train.HMC()
            num_samples = 400
            samples = hmc.sample(self.m, num_samples=num_samples, epsilon=0.05,
                                 lmin=10, lmax=20, thin=10)
            xs = np.array(samples[self.m.x.full_name].tolist(), dtype=np.float32)
            self.assertEqual(samples.shape, (400, 2))
            self.assertEqual(xs.shape, (400, 2))
            assert_almost_equal(xs.mean(0), np.zeros(2), decimal=1)


class CheckTrainingVariableState(GPflowTestCase):
    def setUp(self):
        X, Y = np.random.randn(2, 10, 1)
        self.m = gpflow.models.GPMC(
            X, Y,
            kern=gpflow.kernels.Matern32(1),
            likelihood=gpflow.likelihoods.StudentT())

    def test_last_update(self):
        with self.test_context():
            self.m.compile()
            hmc = gpflow.train.HMC()
            samples = hmc.sample(self.m, num_samples=10, lmin=1, lmax=10, epsilon=0.05, thin=10)
            self.check_last_variables_state(self.m, samples)

    def test_with_fixed(self):
        with self.test_context():
            self.m.kern.lengthscales.trainable = False
            self.m.compile()
            hmc = gpflow.train.HMC()
            samples = hmc.sample(self.m, num_samples=10, lmax=10, epsilon=0.05)
            missing_param = self.m.kern.lengthscales.full_name
            self.assertTrue(missing_param not in samples)
            self.check_last_variables_state(self.m, samples)

    def test_multiple_runs(self):
        with self.test_context():
            self.m.compile()
            hmc = gpflow.train.HMC()
            for n in range(1, 5):
                samples = hmc.sample(self.m, num_samples=n, lmax=10, epsilon=0.05)
                self.check_last_variables_state(self.m, samples)

    def check_last_variables_state(self, m, samples):
        xs = samples.drop('logprobs', axis=1)
        params = {p.full_name: p for p in m.trainable_parameters}
        self.assertEqual(set(params.keys()), set(xs.columns))
        last = xs.iloc[-1]
        for col in last.index:
            assert_almost_equal(last[col], params[col].read_value())


if __name__ == "__main__":
    unittest.main()
