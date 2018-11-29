import logging
import sys

import fire
import numpy as np
import scipy
from matplotlib import pyplot
from scipy.optimize import OptimizeWarning

from brainscore import benchmarks
from brainscore.assemblies import merge_data_arrays
from brainscore.benchmarks import metrics
from brainscore.metrics.ceiling import ceilings
from brainscore.metrics.transformations import CrossValidation
from result_caching import store, cache

logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

_logger = logging.getLogger(__name__)

upto50 = (0.025, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5)
upto90 = upto50 + (0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9)
default_size = .5


def plot(sizes=upto50, size_label='train_size',
         data='dicarlo.Majaj2015', metric='pls_fit', ceiling='splitrep'):
    # compute
    ceilings = []
    for size in sizes:
        _logger.debug("size: {}".format(size))
        score = compute_ceilings(data, metric, ceiling=ceiling, **{size_label: size})
        score = score.expand_dims(size_label)
        score[size_label] = [size]
        ceilings.append(score)
    ceilings = merge_data_arrays(ceilings)

    # plot
    def sigmoid(x, a, b, c):
        return (1 - c) / (1 + np.exp(-b * (x - a)))

    fig, axes = pyplot.subplots(1, 2, figsize=(10, 5))
    for ax, region in zip(axes, np.unique(ceilings['region'])):
        ax.set_title(region)
        x = np.array(sizes)
        score = ceilings.sel(region=region)
        y = score.sel(aggregation='center').values
        err = score.sel(aggregation='error').values
        ax.scatter(x, y)
        ax.errorbar(x, y, err, linestyle='None')

        try:
            fit_params, fit_cov = scipy.optimize.curve_fit(sigmoid, x, y)
            fit_y = sigmoid(x, *fit_params)
            r, p = scipy.stats.pearsonr(y, fit_y)
            if p < 0.05:
                x_fitplot = np.arange(min(x), max(x), (max(x) - min(x)) / 100)
                ax.plot(x_fitplot, sigmoid(x_fitplot, *fit_params))
        except (RuntimeError, OptimizeWarning):
            pass
    ax = fig.add_subplot(111, frameon=False)
    pyplot.tick_params(labelcolor='none', top='off', bottom='off', left='off', right='off')
    ax.set_xlabel(size_label)
    ax.set_ylabel('goodness-of-fit')
    pyplot.tight_layout()
    return fig


def compute_ceilings(assembly_name, metric_name, ceiling, train_size=default_size, test_size=default_size):
    assembly, _, _ = instantiate_benchmark(assembly_name, metric_name)

    scores = []
    dividers = np.unique(assembly['region'])
    for i, region in enumerate(dividers):
        _logger.debug("dividers {}/{}: region={}".format(i + 1, len(dividers), region))
        score = compute_ceiling(assembly_name, metric_name, ceiling=ceiling, region=region,
                                train_size=train_size, test_size=test_size)
        score = score.expand_dims('region')
        score['region'] = [region]
        scores.append(score)
    scores = merge_data_arrays(scores)
    return scores


@store()
def compute_ceiling(assembly, metric, ceiling, train_size, test_size, region):
    _assembly, _metric, average_repetition = instantiate_benchmark(assembly, metric)
    _assembly = _assembly.multisel(region=region)
    ceiling = ceilings[ceiling](metric=_metric, average_repetition=average_repetition,
                                repetition_train_size=train_size, repetition_test_size=test_size)
    score = ceiling(_assembly)
    return score


@cache()
def instantiate_benchmark(data, metric):
    assembly_loader = benchmarks._assemblies[data]
    data = assembly_loader(average_repetition=False)
    metric = metrics[metric]()
    return data, metric, assembly_loader.average_repetition


def per_neuroid_ceiling(assembly_name='dicarlo.Kar2018coco'):
    benchmark = benchmarks.load(assembly_name)
    ceiling = benchmark.ceiling.raw
    ceiling = CrossValidation().aggregate(ceiling)
    x, y, err = ceiling['neuroid_id'], ceiling.sel(aggregation='center'), ceiling.sel(aggregation='error')
    threshold = .9
    pass_threshold = y >= threshold
    pass_threshold = sum(pass_threshold)
    print(f"pass threshold {threshold}: {pass_threshold.values}")

    pyplot.errorbar(x, y, yerr=err, fmt='o')
    pyplot.plot(pyplot.xlim(), [threshold, threshold], 'g--')
    pyplot.xlabel('neuroid_id')
    pyplot.ylabel('internal consistency (spearman-brown corrected pearson)')
    pyplot.savefig(f'results/neuroid_ceiling-{assembly_name}.png')


if __name__ == '__main__':
    fire.Fire()
