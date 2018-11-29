import logging
from typing import Union

from brainscore import benchmarks
from brainscore.metrics import Score
from brainscore.metrics.transformations import CartesianProduct
from brainscore.utils import fullname
from candidate_models import models
from candidate_models.models import model_multi_activations, infer_image_size
from candidate_models.models.implementations import Defaults as DeepModelDefaults
from candidate_models.models.implementations import model_layers
from result_caching import store_xarray

logger = logging.getLogger(__name__)


class Defaults(object):
    benchmark = 'brain-score'


def score_model(model: Union[str, object], model_identifier=None, layers=None,
                weights=DeepModelDefaults.weights,
                pca_components=DeepModelDefaults.pca_components, image_size=None,
                benchmark=Defaults.benchmark, benchmark_identifier=None):
    if layers is None:
        assert isinstance(model, str), "need either known model string or list of layers"
        layers = model_layers[model]

    assert model_identifier is not None or isinstance(model, str), "need either known model string or model_identifier"
    model_identifier = model_identifier or model

    assert benchmark_identifier is not None or isinstance(benchmark, str), \
        "need either known benchmark string or benchmark_identifier"
    benchmark_identifier = benchmark_identifier or benchmark

    image_size = image_size or infer_image_size(model_identifier)

    if benchmark_identifier == 'brain-score':  # Brain-Score does not return layers and would thus fail storing xarray
        return BrainScore()(model=model, model_identifier=model_identifier, layers=layers,
                            weights=weights, pca_components=pca_components, image_size=image_size)

    return _score_model(model=model, model_identifier=model_identifier, layers=layers,
                        benchmark=benchmark, benchmark_identifier=benchmark_identifier,
                        weights=weights, pca_components=pca_components, image_size=image_size)


@store_xarray(combine_fields=[], identifier_ignore=['model', 'layers', 'benchmark'])
def _score_model(model, model_identifier=None, layers=None,
                 benchmark=Defaults.benchmark, benchmark_identifier=Defaults.benchmark,
                 weights=DeepModelDefaults.weights,
                 pca_components=DeepModelDefaults.pca_components, image_size=DeepModelDefaults.image_size):
    if isinstance(benchmark, str):
        logger.info(f'Loading benchmark {benchmark}')
        benchmark = benchmarks.load(benchmark)

    logger.info('Computing activations')
    model_assembly = model_multi_activations(model=model, model_identifier=model_identifier,
                                             weights=weights, multi_layers=layers,
                                             pca_components=pca_components, image_size=image_size,
                                             stimulus_set=benchmark.stimulus_set_name)

    logger.info(f'Scoring {model_identifier} on {benchmark_identifier}')
    cross_layer = CartesianProduct(dividers=['layer'])
    if 'temporal' in benchmark_identifier:
        return benchmark(model_assembly)
    score = cross_layer(model_assembly, apply=benchmark)
    return score


class BrainScore:
    # Brain-Score is a Benchmark too, but due to its compositionality
    # we deem it too different from the Benchmark base class.
    def __init__(self):
        self._logger = logging.getLogger(fullname(self))
        self.name = 'brain-score'
        self._benchmark_identifiers = ['dicarlo.Majaj2015.V4', 'dicarlo.Majaj2015.IT']  # TODO: behavior

    def __call__(self, model: Union[str, object], model_identifier=None, layers=None,
                 weights=DeepModelDefaults.weights,
                 pca_components=DeepModelDefaults.pca_components, image_size=DeepModelDefaults.image_size):
        benchmark_scores = []
        for benchmark in self._benchmark_identifiers:
            self._logger.info(f"Running benchmark {benchmark}")
            score = score_model(model=model, model_identifier=model_identifier, layers=layers,
                                benchmark=benchmark,
                                weights=weights, pca_components=pca_components, image_size=image_size)
            score = score.expand_dims('benchmark')
            score['benchmark'] = [benchmark]
            benchmark_scores.append(score)

        def best_score(score):
            argmax = score.sel(aggregation='center', _select_raw=False).argmax('layer')  # choose best layer
            best_layer = score['layer'][argmax.values]
            score = score.sel(layer=best_layer)
            del score['layer']
            return score

        scores = [best_score(score) for score in benchmark_scores]
        scores = Score.merge(*scores)
        benchmark_scores = Score.merge(*benchmark_scores)
        brain_score = scores.sel(aggregation='center', _select_raw=False).mean()
        score = Score([brain_score.values], coords={'aggregation': ['center']}, dims=['aggregation'])
        score.attrs[Score.RAW_VALUES_KEY] = benchmark_scores
        return score
