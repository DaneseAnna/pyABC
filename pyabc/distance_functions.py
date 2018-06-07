"""
Distance functions
==================

Distance functions measure closeness of observed and sampled data.
For custom distance functions, either pass a plain function to ABCSMC or
subclass the DistanceFunction class if finer grained configuration is required.
"""

import json
import scipy as sp
import numpy as np
from scipy import linalg as la
from abc import ABC, abstractmethod
from typing import List
import logging
from .sampler import Sampler
df_logger = logging.getLogger("DistanceFunction")


class DistanceFunction(ABC):
    """
    Abstract base class for distance functions.

    Any other distance function should inherit from this class.
    """

    def __init__(self, require_initialize: bool=True):
        """
        Default constructor.
        """
        self.require_initialize = require_initialize

    def initialize(self,
                   t: int,
                   sample_from_prior: List[dict],
                   x_0: dict):
        """
        This method is called by the ABCSMC framework before the first
        use of the distance function (in ``new`` and ``load``)
        and can be used to calibrate it to the statistics of the samples.

        The default implementation is to do nothing.

        This function is only called if require_initialize == True.

        Parameters
        ----------

        t: int
            Time point for which to initialize the distance function.

        sample_from_prior: List[dict]
            List of dictionaries containing the summary statistics.

        x_0: dict
            The observed summary statistics.
        """

    def configure_sampler(self, sampler: Sampler):
        """
        This is called by the ABCSMC class and gives the distance function
        the opportunity to configure the sampler.
        For example, the distance function might request the sampler
        to also return rejected particles and their summary statistics
        in order to adapt the distance functions to the statistics
        of the sample.

        The default is to do nothing.

        Parameters
        ----------

        sampler: Sampler
            The Sampler used in ABCSMC.
        """

    def update(self,
               t: int,
               all_sum_stats: List[dict],
               x_0: dict) -> bool:
        """
        Update the distance function. Default: Do nothing.

        Parameters
        ----------

        t: int
            Time point for which to update/create the distance measure.

        all_sum_stats: List[dict]
            List of all summary statistics that should be used to update the
            distance (in particular also rejected ones).

        x_0: dict
            The observed summary statistics.

        Returns
        -------

        is_updated: bool
            True: If distance function has changed compared to hitherto.
            False: If distance function has not changed (default).
        """
        return False

    @abstractmethod
    def __call__(self,
                 t: int,
                 x: dict,
                 x_0: dict) -> float:
        """
        Evaluate, at time point t, the distance of the tentatively sampled
        particle to the measured data.

        Abstract method. This method has to be overwritten by
        all concrete implementations.

        Parameters
        ----------

        t: int
            Time point at which to evaluate the distance.

        x: dict
            Summary statistics of the tentatively sampled parameter.

        x_0: dict
            Summary statistics of the measured data.

        Returns
        -------

        distance: float
            Attributes distance of the tentatively sampled particle
            from the measured data.
        """

    def get_config(self) -> dict:
        """
        Return configuration of the distance function.

        Returns
        -------

        config: dict
            Dictionary describing the distance function.
        """

        return {"name": self.__class__.__name__}

    def to_json(self) -> str:
        """
        Return JSON encoded configuration of the distance function.

        Returns
        -------

        json_str: str
            JSON encoded string describing the distance function.
            The default implementation is to try to convert the dictionary
            returned my ``get_config``.
        """

        return json.dumps(self.get_config())


class NoDistance(DistanceFunction):
    """
    Implements a kind of null object as distance function.

    This can be used as a dummy distance function if e.g. integrated modeling
    is used.

    .. note::
        This distance function cannot be evaluated, so currently it is in
        particular not possible to use an epsilon threshold which requires
        initialization (i.e. eps.require_initialize==True is not possible).
    """

    def __init__(self):
        super().__init__(require_initialize=False)

    def __call__(self,
                 t: int,
                 x: dict,
                 x_0: dict) -> float:
        raise Exception("{} is not intended to be called."
                        .format(self.__class__.__name__))


class SimpleFunctionDistance(DistanceFunction):
    """
    This is a wrapper around a simple function which calculates the distance.
    If a function is passed to the ABCSMC class, then it is converted to
    an instance of the SimpleFunctionDistance class.

    Parameters
    ----------

    function: Callable
        A Callable accepting two parameters, namely summary statistics x and y.
    """

    def __init__(self,
                 function):
        super().__init__(require_initialize=False)
        self.function = function

    def __call__(self,
                 t: int,
                 x: dict,
                 y: dict) -> float:
        return self.function(x, y)

    def get_config(self):
        conf = super().get_config()
        try:
            conf["name"] = self.function.__name__
        except AttributeError:
            try:
                conf["name"] = self.function.__class_.__name__
            except AttributeError:
                pass
        return conf


def to_distance(maybe_distance_function):
    """

    Parameters
    ----------
    maybe_distance_function: either a Callable, which takes two arguments, or
    a DistanceFunction instance.

    Returns
    -------

    """

    if maybe_distance_function is None:
        return NoDistance()

    if isinstance(maybe_distance_function, DistanceFunction):
        return maybe_distance_function

    return SimpleFunctionDistance(maybe_distance_function)


class PNormDistance(DistanceFunction):
    """
    Use weighted p-norm

    .. math::

        d(x, y) =\
         \\left[\\sum_{i} \\left w_i| x_i-y_i \\right|^{p} \\right]^{1/p}

    to compute distances between sets of summary statistics. E.g. set p=2 to
    get a Euclidean distance.

    Parameters
    ----------

    p: float
        p for p-norm. Required p >= 1, p = np.inf allowed (infinity-norm).

    w: dict
        Weights. Dictionary indexed by time points. Each entry contains a
        dictionary of numeric weights, indexed by summary statistics labels.
        If none is passed, a weight of 1 is considered for every summary
        statistic. If no entry is available in w for a given time point,
        the maximum available time point is selected.
    """

    def __init__(self,
                 p: float=2,
                 w: dict=None):
        super().__init__(require_initialize=False)

        if p < 1:
            raise ValueError("It must be p >= 1")
        self.p = p
        self.w = w

    def __call__(self,
                 t: int,
                 x: dict,
                 y: dict) -> float:
        # make sure weights are initialized
        if self.w is None:
            self._set_default_weights(t, x.keys())

        # select last available time point
        if t not in self.w:
            t = max(self.w)

        # extract weights for time point
        w = self.w[t]

        # compute distance
        if self.p == np.inf:
            d = max(abs(w[key]*(x[key]-y[key]))
                    if key in x and key in y else 0
                    for key in w)
        else:
            d = pow(
                sum(pow(abs(w[key]*(x[key]-y[key])), self.p)
                    if key in x and key in y else 0
                    for key in w),
                1/self.p)

        return d

    def _set_default_weights(self,
                             t: int,
                             summary_statistics_keys):
        """
        Init weights to 1 for every summary statistic.
        """
        self.w = {t: {k: 1 for k in summary_statistics_keys}}

    def get_config(self) -> dict:
        return {"name": self.__class__.__name__,
                "p": self.p,
                "w": self.w}


class AdaptivePNormDistance(PNormDistance):
    """
    In the p-norm distance, adapt the weights for each generation, based on
    the previous simulations.

    Parameters
    ----------

    p: float
        p for p-norm. Required p >= 1, p = np.inf allowed (infinity-norm).

    adaptive: bool
        True: Adapt distance after each iteration.
        False: Adapt distance only once at the beginning in initialize().
        This corresponds to a pre-calibration.

    scale_function: Callable
        (data: List, x_0: float) -> scale: float. Computes the scale (i.e.
        inverse weight s = 1 / w) for a given summary statistic. Here, data
        denotes the list of simulated summary statistics, and x_0 the observed
        summary statistic. Implemented are absolute_median_deviation,
        standard_deviation, centered_absolute_median_deviation,
        centered_standard_deviation.
    """

    def __init__(self,
                 p: float=2,
                 adaptive: bool=True,
                 scale_function=None):
        # call p-norm constructor
        super().__init__(p=p,
                         w=None)

        self.require_initialize = True

        self.adaptive = adaptive

        if scale_function is None:
            scale_function = median_absolute_deviation
        self.scale_function = scale_function

    def configure_sampler(self,
                          sampler: Sampler):
        """
        Make the sampler return also rejected summary statistics if required,
        because these are needed to get a better estimate of the summary
        statistic variabilities.

        Parameters
        ----------

        sampler: Sampler
            The sampler employed.
        """
        if self.adaptive:
            sampler.sample_factory.record_all_sum_stats = True

    def initialize(self,
                   t: int,
                   sample_from_prior: List[dict],
                   x_0: dict):
        """
        Initialize weights.
        """
        # update weights from samples
        self._update(t, sample_from_prior, x_0)

    def update(self,
               t: int,
               all_sum_stats: List[dict],
               x_0: dict):
        """
        Update weights based on all simulations.
        """

        if not self.adaptive:
            return False

        self._update(t, all_sum_stats, x_0)

        return True

    def _update(self,
                t: int,
                all_sum_stats: List[dict],
                x_0: dict):
        """
        Here the real update of weights happens.
        """

        # retrieve keys
        keys = all_sum_stats[0].keys()

        # make sure w_list is initialized
        if self.w is None:
            self.w = {}

        n = len(all_sum_stats)

        # to-be-filled-and-appended weights dictionary
        w = {}

        for key in keys:
            if key not in x_0:
                scale = 0
            else:
                # prepare list for key
                current_list = []
                for j in range(n):
                    if key in all_sum_stats[j]:
                        current_list.append(all_sum_stats[j][key])

                # compute scaling
                scale = self.scale_function(data=current_list, x_0=x_0[key])

            # compute weight (inverted scale)
            if np.isclose(scale, 0):
                # This means that either that the summary statistic was not
                # observed, or the simulations were all identical. In either
                # case, it should be safe to ignore this summary statistic.
                w[key] = 0
            else:
                w[key] = 1 / scale

        # normalize weights to have mean 1
        # This has just the effect that eps will decrease more smoothly, but is
        # not important otherwise.
        mean_weight = np.mean(list(w.values()))
        for key in w:
            w[key] /= mean_weight

        # add to w property
        self.w[t] = w

        # logging
        df_logger.debug("update distance weights = {}".format(self.w[t]))

    def get_config(self) -> dict:
        return {"name": self.__class__.__name__,
                "p": self.p,
                "adaptive": self.adaptive,
                "scale_type": self.scale_function.__name__}


def median_absolute_deviation(**kwargs):
    """
    Calculate the sample `median absolute deviation (MAD)
    <https://en.wikipedia.org/wiki/Median_absolute_deviation/>`_, defined as
    median(abs(data - median(data)).

    Parameters
    ----------

    kwargs:
        data: List
            List of data points.

    Returns
    -------

    mad: float
        The median absolute deviation of the data.

    """
    data = np.asarray(kwargs['data'])
    mad = np.median(np.abs(data - np.median(data)))
    return mad


def standard_deviation(**kwargs):
    """
    Calculate the sample `standard deviation (SD)
    <https://en.wikipedia.org/wiki/Standard_deviation/>`_.

    Parameters
    ----------

    kwargs:
        data: List
            List of data points.

    Returns
    -------

    sd: float
        The standard deviation of the data points.
    """
    data = np.asarray(kwargs['data'])
    sd = np.std(data)
    return sd


def absolute_bias(**kwargs):
    """
    Bias of sample to observed value.
    """
    data = np.asarray(kwargs['data'])
    x_0 = kwargs['x_0']
    mean = np.mean(data)
    bias = np.abs(mean - x_0)
    return bias


def sqrt_mean_squared_error(**kwargs):
    """
    Square root of the mean squared error, i.e.
    of the bias squared plus the variance.
    """
    sd = standard_deviation(kwargs)
    bias = bias(kwargs)
    mse = bias**2 + sd**2
    smse = np.sqrt(mse)
    return smse


def centered_median_absolute_deviation(**kwargs):
    """
    Median absolute deviation to observation.

    Parameters
    ----------

    **kwargs:
        data: List
            List of data points.
        x_0: float
            Observed value for the given summary statistic.

    Returns
    -------

    mad: float
        The median absolute deviation of data w.r.t. x_0.
    """
    data = np.asarray(kwargs['data'])
    x_0 = kwargs['x_0']
    mad = np.median(np.abs(data - x_0))
    return mad


def centered_standard_deviation(**kwargs):
    """
    Standard deviation of absolute deviations to observation.

    Parameters
    ----------

    kwargs:
        data: List
            List of data points.
        x_0: float
            Observed value for the given summary statistic.

    Returns
    -------

    sd: float
        The standard absolute deviation of data w.r.t. x_0.
    """
    data = np.asarray(kwargs['data'])
    x_0 = kwargs['x_0']
    sd = np.std(np.abs(data - x_0))
    return sd


class DistanceFunctionWithMeasureList(DistanceFunction):
    """
    Base class for distance functions with measure list.
    This class is not functional on its own.

    Parameters
    ----------

    measures_to_use: Union[str, List[str]].
        * If set to "all", all measures are used. This is the default.
        * If a list is provided, the measures in the list are used.
        * measures refers to the summary statistics.
    """

    def __init__(self,
                 measures_to_use='all'):
        super().__init__(require_initialize=True)
        self._measures_to_use_passed_to_init = measures_to_use
        #: The measures (summary statistics) to use for distance calculation.
        self.measures_to_use = None

    def initialize(self,
                   t: int,
                   sample_from_prior: List[dict],
                   x_0: dict):
        if self._measures_to_use_passed_to_init == 'all':
            self.measures_to_use = sample_from_prior[0].keys()
            raise Exception(
                "distance function from all measures not implemented.")
        else:
            self.measures_to_use = self._measures_to_use_passed_to_init

    def get_config(self):
        config = super().get_config()
        config["measures_to_use"] = self.measures_to_use
        return config


class ZScoreDistanceFunction(DistanceFunctionWithMeasureList):
    """
    Calculate distance as sum of ZScore over the selected measures.
    The measured Data is the reference for the ZScore.

    Hence

    .. math::

        d(x, y) =\
         \\sum_{i \\in \\text{measures}} \\left| \\frac{x_i-y_i}{y_i} \\right|
    """
    def __call__(self,
                 t: int,
                 x: dict,
                 y: dict) -> float:
        return sum(abs((x[key]-y[key])/y[key]) if y[key] != 0 else
                   (0 if x[key] == 0 else np.inf)
                   for key in self.measures_to_use) / len(self.measures_to_use)


class PCADistanceFunction(DistanceFunctionWithMeasureList):
    """
    Calculate distance in whitened coordinates.

    A whitening transformation :math:`X` is calculated from an initial sample.
    The distance is measured as euclidean distance in the transformed space.
    I.e

    .. math::

        d(x,y) = \\| Wx - Wy \\|
    """
    def __init__(self, measures_to_use='all'):
        super().__init__(measures_to_use)
        self._whitening_transformation_matrix = None

    def _dict_to_to_vect(self, x):
        return sp.asarray([x[key] for key in self.measures_to_use])

    def _calculate_whitening_transformation_matrix(self, sample_from_prior):
        samples_vec = sp.asarray([self._dict_to_to_vect(x)
                                  for x in sample_from_prior])
        # samples_vec is an array of shape nr_samples x nr_features
        means = samples_vec.mean(axis=0)
        centered = samples_vec - means
        covariance = centered.T.dot(centered)
        w, v = la.eigh(covariance)
        self._whitening_transformation_matrix = (
            v.dot(sp.diag(1. / sp.sqrt(w))).dot(v.T))

    def initialize(self,
                   t: int,
                   sample_from_prior: List[dict],
                   x_0: dict):
        super().initialize(t, sample_from_prior, x_0)
        self._calculate_whitening_transformation_matrix(sample_from_prior)

    def __call__(self,
                 t: int,
                 x: dict,
                 y: dict) -> float:
        x_vec, y_vec = self._dict_to_to_vect(x), self._dict_to_to_vect(y)
        distance = la.norm(
            self._whitening_transformation_matrix.dot(x_vec - y_vec), 2)
        return distance


class RangeEstimatorDistanceFunction(DistanceFunctionWithMeasureList):
    """
    Abstract base class for distance functions which estimate is based on a
    range.

    It defines the two template methods ``lower`` and ``upper``.

    Hence

    .. math::

        d(x, y) = \
        \\sum_{i \\in \\text{measures}} \\left | \\frac{x_i - y_i}{u_i - l_i}\
          \\right |

    where :math:`l_i` and :math:`u_i` are the lower and upper
    margin for measure :math:`i`.
    """
    @staticmethod
    def lower(parameter_list: List[float]):
        """
        Calculate the lower margin form a list of parameter values.

        Parameters
        ----------
        parameter_list: List[float]
            List of values of a parameter.

        Returns
        -------

        lower_margin: float
            The lower margin of the range calculated from these parameters
        """

    @staticmethod
    def upper(parameter_list: List[float]):
        """
        Calculate the upper margin form a list of parameter values.

        Parameters
        ----------
        parameter_list: List[float]
            List of values of a parameter.

        Returns
        -------

        upper_margin: float
            The upper margin of the range calculated from these parameters
        """

    def __init__(self, measures_to_use='all'):
        super().__init__(measures_to_use)
        self.normalization = None

    def get_config(self):
        config = super().get_config()
        config["normalization"] = self.normalization
        return config

    def _calculate_normalization(self, sample_from_prior):
        measures = {name: [] for name in self.measures_to_use}
        for sample in sample_from_prior:
            for measure in self.measures_to_use:
                measures[measure].append(sample[measure])
        self.normalization = {measure:
                              self.upper(measures[measure])
                              - self.lower(measures[measure])
                              for measure in self.measures_to_use}

    def initialize(self,
                   t: int,
                   sample_from_prior: List[dict],
                   x_0: dict):
        super().initialize(t, sample_from_prior, x_0)
        self._calculate_normalization(sample_from_prior)

    def __call__(self,
                 t: int,
                 x: dict,
                 y: dict) -> float:
        distance = sum(abs((x[key]-y[key])/self.normalization[key])
                       for key in self.measures_to_use)
        return distance


class MinMaxDistanceFunction(RangeEstimatorDistanceFunction):
    """
    Calculate upper and lower margins as max and min of the parameters.
    This works surprisingly well for normalization in simple cases
    """
    @staticmethod
    def upper(parameter_list):
        return max(parameter_list)

    @staticmethod
    def lower(parameter_list):
        return min(parameter_list)


class PercentileDistanceFunction(RangeEstimatorDistanceFunction):
    """
    Calculate normalization 20% and 80% from percentiles as lower
    and upper margins
    """

    PERCENTILE = 20  #: The percentiles

    @staticmethod
    def upper(parameter_list):
        return sp.percentile(parameter_list,
                             100 - PercentileDistanceFunction.PERCENTILE)

    @staticmethod
    def lower(parameter_list):
        return sp.percentile(parameter_list,
                             PercentileDistanceFunction.PERCENTILE)

    def get_config(self):
        config = super().get_config()
        config["PERCENTILE"] = self.PERCENTILE
        return config


class AcceptAllDistance(DistanceFunction):
    """
    Just a mock distance function which always returns -1.
    So any sample should be accepted for any sane epsilon object.

    Can be used for testing.
    """
    def __call__(self,
                 t: int,
                 x: dict,
                 y: dict) -> float:
        return -1


class IdentityFakeDistance(DistanceFunction):
    """
    A fake distance function, which just passes the summary statistics on.
    This class assumes that the model already returns the distance. This can be
    useful in cases where simulating can be stopped early, when during the
    simulation some condition is reached which makes it impossible to accept
    the particle.
    """
    def __call__(self,
                 t: int,
                 x: dict,
                 y: dict):
        return x
