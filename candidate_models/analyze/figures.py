import logging
import os
import sys
import warnings
from typing import Union

import numpy as np
import seaborn
from matplotlib import pyplot
from scipy.stats.stats import pearsonr

from candidate_models.analyze import DataCollector, is_basenet, align

seaborn.set()
seaborn.set_style("whitegrid")
pyplot.rcParams['svg.fonttype'] = 'none'  # avoid individual text letters, https://stackoverflow.com/a/35734729/2225200


class Plot(object):
    def __init__(self, highlighted_models=()):
        self._highlighted_models = highlighted_models

    def __call__(self, ax=None):
        data = self.collect_results()
        ax_given = ax is not None
        if not ax_given:
            fig, ax = self._create_fig()
        self.apply(data, ax=ax)
        self.highlight_models(ax, data)
        self.indicate_correlation(ax, data)
        if not ax_given:
            fig.tight_layout()
            return fig
        return None

    def _create_fig(self):
        return pyplot.subplots(figsize=(10, 5))

    def apply(self, data, ax):
        raise NotImplementedError()

    def get_xye(self, data):
        raise NotImplementedError()

    def collect_results(self):
        data = DataCollector()()
        return data

    def highlight_models(self, ax, data):
        for highlighted_model in self._highlighted_models:
            model_data = data[data['model'] == highlighted_model]
            x, y, error = self.get_xye(model_data)
            if x.size == 0:
                warnings.warn(f"Model {highlighted_model} not found in data")
                continue
            self._highlight(ax, highlighted_model, x, y)

    def _highlight(self, ax, label, x, y):
        xlim, ylim = ax.get_xlim(), ax.get_ylim()
        dx, dy = (xlim[1] - xlim[0]) * 0.02, (ylim[1] - ylim[0]) * 0.02
        ax.plot([x, x + dx], [y, y + dy], color='black', linewidth=1.)
        self._text(ax, x + dx, y + dy, label, fontsize=20)

    def indicate_correlation(self, ax, data):
        x, y, error = self.get_xye(data)
        r, p = pearsonr(x, y)
        significance_threshold = .05
        if p < significance_threshold:
            text = f"r = {r:.2f}"
        else:
            text = "r n.s."
        xlim, ylim = ax.get_xlim(), ax.get_ylim()
        text_x, text_y = xlim[1] - .15 * (xlim[1] - xlim[0]), ylim[0] + .02 * (ylim[1] - ylim[0])
        self._text(ax=ax, x=text_x, y=text_y, label=text)

    def _text(self, ax, x, y, label, **kwargs):
        ax.text(x, y, label, **kwargs)


class BrainScorePlot(Plot):
    def __init__(self, highlighted_models=()):
        super(BrainScorePlot, self).__init__(highlighted_models=highlighted_models)
        self._nonbasenet_color = '#078930'
        self._basenet_color = '#878789'

        self._nonbasenet_alpha = .7
        self._basenet_alpha = 0.3

    def __call__(self, *args, **kwargs):
        with seaborn.plotting_context("paper", font_scale=2):
            return super(BrainScorePlot, self).__call__(*args, **kwargs)

    def _create_fig(self):
        return pyplot.subplots(figsize=(10, 8))

    def get_xye(self, data, get_models=False):
        imagenet_data = data[data['benchmark'] == 'ImageNet']
        benchmark_data = data[data['benchmark'] == 'Brain-Score']
        imagenet_data = align(imagenet_data, benchmark_data, on='model')
        x = imagenet_data['score'].values.squeeze()
        y, yerr = benchmark_data['score'].values.squeeze(), benchmark_data['error'].values.squeeze()
        if not get_models:
            return x, y, yerr
        return x, y, yerr, imagenet_data['model'].values

    def apply(self, data, ax):
        x, y, error, models = self.get_xye(data, get_models=True)
        color = [self._nonbasenet_color if not is_basenet(model) else self._basenet_color
                 for model in models]
        alpha = [self._nonbasenet_alpha if not is_basenet(model) else self._basenet_alpha
                 for model in models]
        self.plot(x=x, y=y, color=color, alpha=alpha, ax=ax)
        ax.set_xlabel('Imagenet performance (% top-1)')
        ax.set_ylabel('Brain-Score')
        seaborn.despine(ax=ax, top=True, right=True)

    def plot(self, x, y, ax, error=None, label=None,
             color: Union[float, list] = None, marker_size=50, alpha: Union[float, list] = 0.3):
        def _plot(_x, _y, _error, color, alpha):
            # if alpha is a list, provide a way to plot every point separately
            ax.scatter(_x, _y, label=label, color=color, alpha=alpha, s=marker_size)
            if error:
                ax.errorbar(_x, _y, _error, label=label, color=color, alpha=alpha,
                            elinewidth=1, linestyle='None')

        if isinstance(alpha, float) and isinstance(color, float):
            _plot(x, y, error, color=color, alpha=alpha)
        else:
            for _x, _y, _error, _color, _alpha in zip(
                x, y, error if error is not None else [None] * len(x), color, alpha):
                _plot(_x, _y, _error, color=_color, alpha=_alpha)

    def _highlight(self, ax, label, x, y):
        if x > 72:
            return
        return super(BrainScorePlot, self)._highlight(ax=ax, label=label, x=x, y=y)


class BrainScoreZoomPlot(BrainScorePlot):
    def collect_results(self):
        data = super(BrainScoreZoomPlot, self).collect_results()
        imagenet_data = data[data['benchmark'] == 'ImageNet']
        imagenet_data = imagenet_data[imagenet_data['score'] > 70]
        data = data[data['model'].isin(imagenet_data['model'])]
        return data

    def plot(self, *args, marker_size=300, **kwargs):
        super(BrainScoreZoomPlot, self).plot(*args, marker_size=marker_size, **kwargs)

    def _highlight(self, ax, label, x, y):
        return Plot._highlight(self=self, ax=ax, label=label, x=x, y=y)

    def _text(self, ax, x, y, label, **kwargs):
        kwargs = {**kwargs, **dict(fontsize=30)}
        super(BrainScoreZoomPlot, self)._text(ax=ax, x=x, y=y, label=label, **kwargs)


class IndividualPlot(Plot):
    def __init__(self, benchmark, ceiling, highlighted_models=()):
        super(IndividualPlot, self).__init__(highlighted_models=highlighted_models)
        self._benchmark = benchmark
        self._ceiling = ceiling
        self._plot_ceiling = True

    def collect_results(self):
        data = super().collect_results()
        data = data[~data['model'].isin(['cornet_z', 'cornet_r', 'cornet_r2'])]
        data = data[data.apply(lambda row: not is_basenet(row['model']), axis=1)]
        return data

    def __call__(self, *args, plot_ceiling=True, **kwargs):
        self._plot_ceiling = plot_ceiling
        super(IndividualPlot, self).__call__(*args, **kwargs)

    def get_xye(self, data):
        imagenet_data = data[data['benchmark'] == 'ImageNet']
        benchmark_data = data[data['benchmark'] == self._benchmark]
        imagenet_data = align(imagenet_data, benchmark_data, on='model')
        x = imagenet_data['score'].values.squeeze()
        y, yerr = benchmark_data['score'].values.squeeze(), benchmark_data['error'].values.squeeze()
        return x, y, yerr

    def apply(self, data, ax):
        x, y, error = self.get_xye(data)

        self._plot(x=x, y=y, error=error, ax=ax)
        ax.grid(b=True, which='major', linewidth=0.5)
        self._despine(ax)

    def _despine(self, ax):
        seaborn.despine(ax=ax, top=True, right=True)

    def _plot(self, x, y, ax, error=None, alpha=0.7, s=20, **kwargs):
        ax.scatter(x, y, alpha=alpha, s=s, **kwargs)
        if error is not None:
            ax.errorbar(x, y, error, elinewidth=1, linestyle='None', alpha=alpha, **kwargs)
        if self._plot_ceiling and self._ceiling:
            ax.plot(ax.get_xlim(), [self._ceiling, self._ceiling], linestyle='dashed', linewidth=1., color='gray')

    def _text(self, ax, x, y, label, **kwargs):
        kwargs = {**kwargs, **dict(fontsize=10)}
        super(IndividualPlot, self)._text(ax=ax, x=x, y=y, label=label, **kwargs)


class V1Plot(IndividualPlot):
    def __init__(self, highlighted_models=()):
        super(V1Plot, self).__init__(ceiling=None, highlighted_models=highlighted_models)

    def apply(self, data, ax):
        super(V1Plot, self).apply(data, ax)
        ax.set_title('V1')
        ax.set_ylabel('Neural Predictivity')

    def _plot(self, *args, **kwargs):
        super(V1Plot, self)._plot(*args, **kwargs, color='#CFE9FF')


class V4Plot(IndividualPlot):
    def __init__(self, highlighted_models=()):
        super(V4Plot, self).__init__(benchmark='dicarlo.Majaj2015.V4', ceiling=.892,
                                     highlighted_models=highlighted_models)

    def apply(self, data, ax):
        super(V4Plot, self).apply(data, ax)
        ax.set_title('V4')
        ax.set_ylabel('Neural Predictivity')
        # for tk in ax.get_yticklabels():
        #     tk.set_visible(False)

    def _plot(self, *args, **kwargs):
        super(V4Plot, self)._plot(*args, **kwargs, color='#89B8E0')


class ITPlot(IndividualPlot):
    def __init__(self, highlighted_models=()):
        super(ITPlot, self).__init__(benchmark='dicarlo.Majaj2015.IT', ceiling=.817,
                                     highlighted_models=highlighted_models)

    def apply(self, data, ax):
        super(ITPlot, self).apply(data, ax)
        ax.set_title('IT')
        for tk in ax.get_yticklabels():
            tk.set_visible(False)

    def _plot(self, *args, **kwargs):
        super(ITPlot, self)._plot(*args, **kwargs, color='#679BC7')


class BehaviorPlot(IndividualPlot):
    def __init__(self, highlighted_models=()):
        super(BehaviorPlot, self).__init__(benchmark='dicarlo.Rajalingham2018', ceiling=.479,
                                           highlighted_models=highlighted_models)

    def apply(self, data, ax):
        super(BehaviorPlot, self).apply(data, ax)
        ax.set_title('Behavior')
        ax.yaxis.tick_right()
        ax.set_ylabel('Behavioral Predictivity', rotation=270, labelpad=15)
        ax.yaxis.set_label_position("right")

    def _despine(self, ax):
        seaborn.despine(ax=ax, left=True, top=True, right=False)
        ax.tick_params(axis='y', which='both', length=0)

    def _plot(self, *args, **kwargs):
        super(BehaviorPlot, self)._plot(*args, **kwargs, color='#4C778E')


class IndividualPlots(object):
    def __init__(self, highlighted_models=(), plot_ceilings=True):
        self._highlighted_models = highlighted_models
        self._plot_ceilings = plot_ceilings

    def __call__(self):
        fig = pyplot.figure(figsize=(10, 4))
        self.apply(fig)
        fig.tight_layout()
        return fig

    def apply(self, fig):
        plotters = [
            # V1Plot(highlighted_models=self._highlighted_models),
            V4Plot(highlighted_models=self._highlighted_models),
            ITPlot(highlighted_models=self._highlighted_models),
            BehaviorPlot(highlighted_models=self._highlighted_models)
        ]
        axes = []
        for i, plotter in enumerate(plotters):
            # ax = fig.add_subplot(1, len(plotters), i + 1, sharey=None if i in [0, 3] else axes[0])
            ax = fig.add_subplot(1, len(plotters), i + 1, sharey=None if i in [0, 2] else axes[0])
            axes.append(ax)
            plotter(ax=ax, plot_ceiling=self._plot_ceilings)

        # joint xlabel
        ax = fig.add_subplot(111, frameon=False)
        ax.grid('off')
        ax.tick_params(labelcolor='none', top='off', bottom='off', left='off', right='off')
        ax.set_xlabel('Imagenet performance (% top-1)', labelpad=5)


class PaperFigures(object):
    def __init__(self):
        self._savedir = os.path.join(os.path.dirname(__file__), '..', '..', 'results')
        self._save_formats = ['svg', 'pdf', 'png']

    def __call__(self):
        highlighted_models = [
            "cornet_s",  # CORnet
            'resnet-101_v2', 'resnet-152_v2',  # ResNet family
            'densenet-169', 'densenet-201',  # best ML
            'pnasnet_large',  # good ImageNet performance
            'alexnet',  # historic
            'mobilenet_v2_1.0_224',  #'mobilenet_v2_0.75_224',  # best mobilenet
            'mobilenet_v1_1.0.224',  # good IT
            'inception_v4',  # good i2n
            'vgg-19',  # good V4
            'xception',  # good V4
        ]

        figs = {
            'brain-score': BrainScorePlot(highlighted_models=highlighted_models),
            'brain-score-zoom': BrainScoreZoomPlot(highlighted_models=highlighted_models),
            # 'individual': IndividualPlots(highlighted_models=highlighted_models, plot_ceilings=False),
        }
        for name, fig_maker in figs.items():
            fig = fig_maker()
            self.save(fig, name)

    def save(self, fig, name):
        for extension in self._save_formats:
            savepath = os.path.join(self._savedir, f"{name}.{extension}")
            fig.savefig(savepath, format=extension)
            print("Saved to", savepath)


if __name__ == '__main__':
    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
    plotter = PaperFigures()
    plotter()
