from typing import List, Callable
import pandas
from pyabc.parameters import Parameter

class Particle:
    """
    An (accepted) particle, containing the information that will also be
    stored in the database.

    Properties
    ----------

    m: int
        The model nr

    parameter: Parameter
        The model specific parameter

    weight: float, 0 < weight < 1
        The weight of the particle

    distance_list: List[float]
        A particle can contain more than one sample.
        If so, the distances of the individual samples
        are stored in this list. In the most common case of a single
        sample, this list has length 1.

    summary_statistics_list
        List of summary statistics which describe the sample
        This list is usually of length 1. This list is longer only if more
        than one sample is taken for a particle.

    """

    def __init__(self, m: int,
                 parameter: Parameter,
                 weight: float = 0,
                 distance_list: List[float] = None,
                 summary_statistics_list: List[dict] = None):
        self.m = m
        self.parameter = parameter
        self.weight = weight
        self.distance_list = distance_list
        self.summary_statistics_list = summary_statistics_list

    def __getitem__(self, item):
        return getattr(self, item)

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def __eq__(self, other):
        for key in ["m", "parameter", "weight", "distance_list",
                    "summary_statistics_list"]:
            if self[key] != other[key]:
                return False
        return True


class FullInfoParticle(Particle):
    """
    Derives from Particle and in addition stores all summary statistics that
    were generated during the creation of this particle, and a flag
    indicating whether this particle was accepted or not.

    Properties
    ----------

    all_summary_statistics_list: List[dict]
        List of all summary statistics generated during the creation of this
        particle (also when they led to rejection).

    accepted: bool
        True if particle was accepted, False if not.
    """

    def __init__(self, m: int,
                 parameter: Parameter,
                 weight: float = 0,
                 distance_list: List[float] = None,
                 summary_statistics_list: List[dict] = None,
                 all_summary_statistics_list: List[dict] = None,
                 accepted: bool = True):
        super().__init__(m, parameter, weight, distance_list,
                         summary_statistics_list)
        self.all_summary_statistics_list = all_summary_statistics_list
        self.accepted = accepted

    def __eq__(self, other):
        return (super().__eq__(other) and
                self["all_summary_statistics_list"]
                == other["all_summary_statistics_list"])

    def to_particle(self) -> Particle:
        """
        Reduce to Particle by forgetting all_summary_statistics_list and
        accepted flag.

        :return:
        particle: Particle
            The reduced representation.
        """
        particle = Particle(self.m, self.parameter, self.weight,
                            self.distance_list, self.summary_statistics_list)
        return particle


class Population:
    """
    This class acts as as a wrapper around a list of particles, offering
    standardized interfaces.

    Usage note:
    First, all particles should be appended to the population, via append().
    Then, normalize_weights() should be called once to normalize the weights of
    the particles for each model, and compute the model probabilities.
    Thereafter, calling get_weighted_distances() makes sense. The function
    update_distances() can be called as any point as it has no influence on
    the weights.
    """

    def __init__(self, particle_list: List[Particle] =None):
        if particle_list is None:
            self._list = []
        else:
            self._list = particle_list.copy()
        self._is_normalized = False
        self._model_probabilities = None

        # TODO
        # the is_normalized is not nice, maybe we can split into classes
        # Population and NormalizedPopulation, making a deep copy, but it
        # works like this for now

    def __add__(self, other):
        """
        Should only be called before normalization.
        """

        population = Population()
        population._list = self.get_list() + other.get_list()

        return population

    def get_list(self) -> List[Particle]:
        """
        Get a copy of the underlying particle list.
        :return:
            A copied particle list.
        """
        return self._list.copy()

    def is_normalized(self):
        return self._is_normalized

    def append(self, particle: Particle):
        """
        Append a particle to the list.
        :param particle: Particle
            Particle to be appended.
        """
        self._list.append(particle)

    def normalize_weights(self):
        """
        Normalize the cumulative weight of the particles belonging to a model
        to 1, and compute the model probabilities. Should only be called once.
        """

        # Create empty dictionary. Keys will be the models.
        store = dict()
        for particle in self._list:
            if particle is not None:
                # setdefault: similar to get(), sets dict[key] = default if key
                # is not in dict yet.
                store.setdefault(particle.m, []).append(particle)
            else:
                print("ABC History warning: Empty particle")

        model_total_weights = {m: sum(particle.weight for particle in plist)
                               for m, plist in store.items()}
        population_total_weight = sum(model_total_weights.values())
        model_probabilities = {m: w / population_total_weight
                               for m, w in model_total_weights.items()}

        # update model_probabilities attribute
        self._model_probabilities = model_probabilities

        # normalize weights within each model
        for m in store:
            model_total_weight = model_total_weights[m]
            plist = store[m]
            for particle in plist:
                particle.weight /= model_total_weight

        self._is_normalized = True

    def update_distances(self,
                         distance_to_ground_truth: Callable[[dict], float]):
        """
        Update the distances of all summary statistics of all particles
        according to the passed distance function (which is typically
        different from the distance function with which the original
        distances were computed).

        :param distance_to_ground_truth:
            Distance function to the observed summary statistics.
        """
        for particle in self._list:
            for i in range(len(particle.distance_list)):
                particle.distance_list[i] = \
                    distance_to_ground_truth(
                        particle.summary_statistics_list[i])

    def get_model_probabilities(self) -> dict:
        """
        Get probabilities of the individual models.
        :return:
        """
        # _model_probabilities are assigned during normalization
        if not self._is_normalized:
            self.normalize_weights()
        return self._model_probabilities

    def get_weighted_distances(self) -> pandas.DataFrame:
        """
        Create iteration of distances and weights. All weights will sum to 1.

        :return:
            A pandas.DataFrame containing in column 'distance' the distances
            and in column 'weight' the scaled weights.
        """

        # create pandas.DataFrame of distances and weights
        rows = []
        for particle in self._list:
            model_probability = self._model_probabilities[particle.m]
            for distance in particle.distance_list:
                rows.append({'distance': distance,
                             'w': particle.weight * model_probability})

        df = pandas.DataFrame(rows)
        return df

    def to_dict(self) -> dict:
        """
        Create a dictionary representation, creating a list of particles for
        each model.

        :return:
            A dictionary with the models as keys and a list of particles for
            each model as values.
        """

        store = dict()
        population = self._list.copy()

        for particle in population:
            if particle is not None:
                # setdefault: similar to get(), sets dict[key] = default if key
                # is not in dict yet.
                store.setdefault(particle.m, []).append(particle)
            else:
                print("ABC History warning: Empty particle")

        return store