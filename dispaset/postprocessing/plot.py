import logging
import sys

import numpy as np
import pandas as pd
import pickle
import matplotlib
import matplotlib.pyplot as plt
import networkx as nx
import cartopy
import cartopy.crs as ccrs
import cartopy.mpl.geoaxes
import cartopy.io.img_tiles as cimgt
import requests

from matplotlib.patches import Wedge, Circle
from matplotlib.collections import LineCollection, PatchCollection
from matplotlib.patches import FancyArrow

from ..misc.str_handler import clean_strings
from ..common import commons

from .postprocessing import get_imports, get_plot_data, filter_by_zone, filter_by_tech, filter_by_storage, \
                            get_power_flow_tracing, get_from_to_flows, get_net_positions, get_EFOH, CostExPost


def plot_dispatch(demand, plotdata, level=None, curtailment=None, shedload=None, shiftedload=None, rng=None,
                  alpha=None, figsize=(13, 6)):
    """
    Function that plots the dispatch data and the reservoir level as a cumulative sum

    :param demand:      Pandas Series with the demand curve
    :param plotdata:    Pandas Dataframe with the data to be plotted. Negative columns should be at the beginning. Output of the function GetPlotData
    :param level:       Optional pandas series/dataframe with an (dis)aggregated reservoir level for the considered zone.
    :param curtailment: Optional pandas series with the value of the curtailment
    :param shedload:    Optional pandas series with the value of the shed load
    :param rng:         Indexes of the values to be plotted. If undefined, the first week is plotted
    """
    import matplotlib.patches as mpatches
    import matplotlib.lines as mlines

    pd.plotting.register_matplotlib_converters()

    if rng is None:
        pdrng = plotdata.index[:min(len(plotdata) - 1, 7 * 24)]
    elif not type(rng) == type(demand.index):
        logging.error('The "rng" variable must be a pandas DatetimeIndex')
        raise ValueError()
    elif rng[0] < plotdata.index[0] or rng[0] > plotdata.index[-1] or rng[-1] < plotdata.index[0] or rng[-1] > \
            plotdata.index[-1]:
        logging.warning('Plotting range is not properly defined, considering the first simulated week')
        pdrng = plotdata.index[:min(len(plotdata) - 1, 7 * 24)]
    else:
        pdrng = rng

    # Netting the interconnections:
    if 'FlowIn' in plotdata and 'FlowOut' in plotdata:
        plotdata['FlowOut'], plotdata['FlowIn'] = (np.minimum(0, plotdata['FlowIn'] + plotdata['FlowOut']),
                                                   np.maximum(0, plotdata['FlowOut'] + plotdata['FlowIn']))

    # find the zero line position:
    cols = plotdata.columns.tolist()
    idx_zero = 0
    tmp = plotdata.iloc[:, idx_zero].mean()
    while tmp <= 0 and idx_zero < len(cols) - 1:
        idx_zero += 1
        tmp = plotdata.iloc[:, idx_zero].mean()

    tmp = plotdata[cols[:idx_zero]].sum(axis=1)
    sumplot_neg = pd.DataFrame()
    sumplot_neg['sum'] = tmp
    tmp2 = plotdata[cols[:idx_zero]]
    for col in tmp2:
        sumplot_neg[col] = - tmp2[col]
    sumplot_neg = sumplot_neg.cumsum(axis=1)

    sumplot_pos = plotdata[cols[idx_zero:]].cumsum(axis=1)
    sumplot_pos['zero'] = 0
    sumplot_pos = sumplot_pos[['zero'] + sumplot_pos.columns[:-1].tolist()]

    fig, axes = plt.subplots(nrows=2, ncols=1, sharex=True, figsize=(figsize), frameon=True,  # 14 4*2
                             gridspec_kw={'height_ratios': [2.7, .8], 'hspace': 0.04})

    # Create left axis:
    #    ax.set_ylim([-10000,15000])
    axes[0].plot(pdrng, demand[pdrng], color='k')
    axes[0].set_xlim(pdrng[0], pdrng[-1])

    fig.suptitle('Power dispatch for zone ' + demand.name[1])

    # Define labels, patches and colors
    labels = []
    patches = []
    colorlist = []

    # Plot reservoir levels (either separated or as one value)
    if level is not None:
        if isinstance(level, pd.DataFrame):
            cols_lvl = level.columns.tolist()
            sumplot_lev = level[cols_lvl[0:]].cumsum(axis=1)
            sumplot_lev['zero'] = 0
            sumplot_lev = sumplot_lev[['zero'] + sumplot_lev.columns[:-1].tolist()]
            for j in range(len(sumplot_lev.columns) - 1):
                col3 = sumplot_lev.columns[j]
                col4 = sumplot_lev.columns[j + 1]
                rez_color = commons['colors'][col4]
                rez_hatch = commons['hatches'][col4]
                axes[1].plot(pdrng, sumplot_lev.loc[pdrng, col4], color='k', alpha=alpha, linestyle=':')
                axes[1].fill_between(pdrng, sumplot_lev.loc[pdrng, col3], sumplot_lev.loc[pdrng, col4],
                                     facecolor=rez_color, alpha=0.3)
                labels.append(col4)
                patches.append(mpatches.Patch(facecolor=rez_color, alpha=0.3, label=col4))
                colorlist.append(rez_color)
        elif isinstance(level, pd.Series):
            # Create lower axis:
            axes[1].plot(pdrng, level[pdrng], color='k', alpha=alpha, linestyle=':')
            axes[1].fill_between(pdrng, 0, level[pdrng],
                                 facecolor=commons['colors']['WAT'], alpha=.3)
        axes[1].set_ylabel('Level [GWh]')
        axes[1].yaxis.label.set_fontsize(12)
        line_SOC = mlines.Line2D([], [], color='black', alpha=alpha, label='Reservoir', linestyle=':')

    # Plot negative values:
    for j in range(idx_zero):
        col1 = sumplot_neg.columns[j]
        col2 = sumplot_neg.columns[j + 1]
        color = commons['colors'][col2]
        hatch = commons['hatches'][col2]
        axes[0].fill_between(pdrng, sumplot_neg.loc[pdrng, col1], sumplot_neg.loc[pdrng, col2], facecolor=color,
                             alpha=alpha, hatch=hatch)
        if col2 not in labels:
            labels.append(col1)
            patches.append(mpatches.Patch(facecolor=color, alpha=alpha, hatch=hatch, label=col2))
            colorlist.append(color)

    # Plot Positive values:
    for j in range(len(sumplot_pos.columns) - 1):
        col1 = sumplot_pos.columns[j]
        col2 = sumplot_pos.columns[j + 1]
        color = commons['colors'][col2]
        hatch = commons['hatches'][col2]
        axes[0].fill_between(pdrng, sumplot_pos.loc[pdrng, col1], sumplot_pos.loc[pdrng, col2], facecolor=color,
                             alpha=alpha,
                             hatch=hatch)
        labels.append(col2)
        patches.append(mpatches.Patch(facecolor=color, alpha=alpha, hatch=hatch, label=col2))
        colorlist.append(color)

    # Plot curtailment:
    if isinstance(curtailment, pd.Series):
        if not curtailment.index.equals(demand.index):
            logging.error('The curtailment time series must have the same index as the demand')
            sys.exit(1)
        axes[0].fill_between(pdrng, sumplot_neg.loc[pdrng, 'sum'] - curtailment[pdrng], sumplot_neg.loc[pdrng, 'sum'],
                             facecolor=commons['colors']['curtailment'])
        labels.append('Curtailment')
        patches.append(mpatches.Patch(facecolor=commons['colors']['curtailment'], label='Curtailment'))

    axes[0].set_ylabel('Power [GW]')
    axes[0].yaxis.label.set_fontsize(12)

    load_change = pd.Series(0, index=demand.index)
    load_changed = False
    if isinstance(shedload, pd.Series):
        if not shedload.index.equals(demand.index):
            logging.critical('The shedload time series must have the same index as the demand')
            sys.exit(1)
        load_change += -shedload
        load_changed = True
    if isinstance(shiftedload, pd.Series):
        if not shiftedload.index.equals(demand.index):
            logging.critical('The shiftedload time series must have the same index as the demand')
            sys.exit(1)
        load_change += -shiftedload
        load_changed = True
    reduced_demand = demand + load_change
    axes[0].plot(pdrng, reduced_demand[pdrng], color='k', alpha=alpha, linestyle='dashed')
    line_shedload = mlines.Line2D([], [], color='black', alpha=alpha, label='New load', linestyle='dashed')

    line_demand = mlines.Line2D([], [], color='black', label='Load')
    # plt.legend(handles=[line_demand] + patches[::-1], loc=4)

    if not load_changed and level is None:
        plt.legend(handles=[line_demand] + patches[::-1], loc=4, bbox_to_anchor=(1.2, 0.5))
    elif not load_changed:
        plt.legend(handles=[line_demand] + [line_SOC] + patches[::-1], loc=4, bbox_to_anchor=(1.2, 0.5))
    elif level is None:
        plt.legend(handles=[line_demand] + [line_shedload] + patches[::-1], loc=4, bbox_to_anchor=(1.2, 0.5))
        axes[0].fill_between(demand.index, demand, reduced_demand, facecolor="none", hatch="X", edgecolor="k",
                             linestyle='dashed')
    else:
        plt.legend(title='Dispatch for ' + demand.name[1], handles=[line_demand] + [line_shedload] + [line_SOC] +
                                                                   patches[::-1], loc=4, bbox_to_anchor=(1.2, 0.5))
        axes[0].fill_between(demand.index, demand, reduced_demand, facecolor="none", hatch="X", edgecolor="k",
                             linestyle='dashed')

    plt.subplots_adjust(right=0.8)
    plt.show()


def plot_rug(df_series, on_off=False, cmap='Greys', fig_title='', normalized=False):
    """Create multiaxis rug plot from pandas Dataframe

    Arguments:
        df_series (pd.DataFrame): 2D pandas with timed index
        on_off (bool): if True all points that are above 0 will be plotted as one color. If False all values will be colored based on their value.
        cmap (str): palette name (from colorbrewer, matplotlib etc.)
        fig_title (str): Figure title
        normalized (bool): if True, all series colormaps will be normalized based on the maximum value of the dataframe
    Returns:
        plot

    Function copied from enlopy v0.1 www.github.com/kavvkon/enlopy. Install with `pip install enlopy` for latest version.
    """

    def format_axis(iax):
        # Formatting: remove all lines (not so elegant)
        for spine in ['top', 'right', 'left', 'bottom']:
            iax.axes.spines[spine].set_visible(False)
        # iax.xaxis.set_ticks_position('none')
        iax.yaxis.set_ticks_position('none')
        iax.get_yaxis().set_ticks([])
        iax.yaxis.set_label_coords(-.05, -.1)

    def flag_operation(v):
        if np.isnan(v) or v == 0:
            return False
        else:
            return True

    # check if Series or dataframe
    if isinstance(df_series, pd.DataFrame):
        rows = len(df_series.columns)
    elif isinstance(df_series, pd.Series):
        df_series = df_series.to_frame()
        rows = 1
    else:
        raise ValueError("Has to be either Series or Dataframe")
    if len(df_series) < 1:
        raise ValueError("Has to be non empty Series or Dataframe")

    max_color = np.nanmax(df_series.values)
    min_color = np.nanmin(df_series.values)

    __, axes = plt.subplots(nrows=rows, ncols=1, sharex=True,
                            figsize=(16, 0.25 * rows), squeeze=False,
                            frameon=True, gridspec_kw={'hspace': 0.15})

    for (item, iseries), iax in zip(df_series.iteritems(), axes.ravel()):
        format_axis(iax)
        iax.set_ylabel(str(item)[:30], rotation='horizontal',
                       rotation_mode='anchor',
                       horizontalalignment='right', x=-0.01)
        x = iseries.index

        if iseries.sum() > 0:  # if series is not empty
            if on_off:
                i_on_off = iseries.apply(flag_operation).replace(False, np.nan)
                i_on_off.plot(ax=iax, style='|', lw=.7, cmap=cmap)
            else:
                y = np.ones(len(iseries))
                # Define (truncated) colormap:
                if not normalized:  # Replace max_color (frame) with series max
                    max_color = np.nanmax(iseries.values)
                    min_color = np.nanmin(iseries.values)
                # Hack to plot max color when all series are equal
                if np.isclose(min_color, max_color):
                    min_color = min_color * 0.99

                iax.scatter(x, y,
                            marker='|', s=100,
                            c=iseries.values,
                            vmin=min_color,
                            vmax=max_color,
                            cmap=cmap)

    axes.ravel()[0].set_title(fig_title)
    axes.ravel()[-1].spines['bottom'].set_visible(True)
    axes.ravel()[-1].set_xlim(np.min(x), np.max(x))


def plot_energy_zone_fuel(inputs, results, PPindicators):
    """
    Plots the generation for each zone, disaggregated by fuel type

    :param results:         Dictionnary with the outputs of the model (output of the function GetResults)
    :param PPindicators:    Por powerplant statistics (output of the function get_indicators_powerplant)
    """
    fuels = PPindicators.Fuel.unique()
    zones = PPindicators.Zone.unique()

    GenPerZone = pd.DataFrame(index=zones, columns=fuels)
    # First make sure that all fuels are present. If not, initialize an empty series
    for f in commons['Fuels'] + ['FlowIn']:
        if f not in GenPerZone:
            GenPerZone[f] = 0
    for z in zones:
        for f in fuels:
            tmp = PPindicators[(PPindicators.Fuel == f) & (PPindicators.Zone == z)]
            GenPerZone.loc[z, f] = tmp.Generation.sum()
        NetImports = get_imports(results['OutputFlow'], z)
        if NetImports > 0:
            GenPerZone.loc[z, 'FlowIn'] = NetImports

    cols = [col for col in commons['MeritOrder'] if col in GenPerZone]
    GenPerZone = GenPerZone[cols] / 1E6
    colors = [commons['colors'][tech] for tech in GenPerZone.columns]
    ax = GenPerZone.plot(kind="bar", figsize=(12, 8), stacked=True, color=colors, alpha=0.8, legend='reverse',
                         title='Generation per zone (the horizontal lines indicate the demand)')
    ax.set_ylabel('Generation [TWh]')
    demand = inputs['param_df']['Demand']['DA'].sum() / 1E6
    ax.barh(demand, left=ax.get_xticks() - 0.4, width=[0.8] * len(demand), height=ax.get_ylim()[1] * 0.005, linewidth=2,
            color='k')
    plt.show()
    return GenPerZone


def plot_zone_capacities(inputs, plot=True):
    """
    Plots the installed capacity for each zone, disaggregated by fuel type

    :param inputs:         Dictionnary with the inputs of the model (output of the function GetResults)
    """
    units = inputs['units']
    ZoneFuels = {}
    for u in units.index:
        ZoneFuels[(units.Zone[u], units.Fuel[u])] = (units.Zone[u], units.Fuel[u])

    PowerCapacity = pd.DataFrame(columns=inputs['sets']['f'], index=inputs['sets']['n'])
    StorageCapacity = pd.DataFrame(columns=inputs['sets']['f'], index=inputs['sets']['n'])
    for n, f in ZoneFuels:
        idx = ((units.Zone == n) & (units.Fuel == f))
        PowerCapacity.loc[n, f] = (units.PowerCapacity[idx] * units.Nunits[idx]).sum()
        StorageCapacity.loc[n, f] = (units.StorageCapacity[idx] * units.Nunits[idx]).sum()

    cols = [col for col in commons['MeritOrder'] if col in PowerCapacity]
    PowerCapacity = PowerCapacity[cols]
    if plot:
        colors = [commons['colors'][tech] for tech in PowerCapacity.columns]
        ax = PowerCapacity.plot(kind="bar", figsize=(12, 8), stacked=True, color=colors, alpha=0.8, legend='reverse',
                                title='Installed capacity per zone (the horizontal lines indicate the peak demand)')
        ax.set_ylabel('Capacity [MW]')
        demand = inputs['param_df']['Demand']['DA'].max()
        ax.barh(demand, left=ax.get_xticks() - 0.4, width=[0.8] * len(demand), height=ax.get_ylim()[1] * 0.005,
                linewidth=2,
                color='k')
    return {'PowerCapacity': PowerCapacity, 'StorageCapacity': StorageCapacity}


def plot_zone(inputs, results, z='', rng=None, rug_plot=True):
    """
    Generates plots from the dispa-SET results for one specific zone

    :param inputs:      DispaSET inputs
    :param results:     DispaSET results
    :param z:           Considered zone (e.g. 'BE')
    """
    if z == '':
        Nzones = len(inputs['sets']['n'])
        z = inputs['sets']['n'][np.random.randint(Nzones)]
        print('Randomly selected zone for the detailed analysis: ' + z)
    elif z not in inputs['sets']['n']:
        logging.critical('Zone ' + z + ' is not in the results')
        Nzones = len(inputs['sets']['n'])
        z = inputs['sets']['n'][np.random.randint(Nzones)]
        logging.critical('Randomly selected zone: ' + z)

    plotdata = get_plot_data(inputs, results, z) / 1000  # GW

    aggregation = False
    if 'OutputStorageLevel' in results:
        lev = filter_by_zone(results['OutputStorageLevel'], inputs, z)
        lev = lev * inputs['units']['StorageCapacity'].loc[lev.columns] / 1e3  # GWh of storage
        for col in lev.columns:
            if 'BEVS' in col:
                lev[col] = lev[col] * inputs['param_df']['AvailabilityFactor'][col]
        level = filter_by_storage(lev, inputs, StorageSubset='s')
        levels = pd.DataFrame(index=results['OutputStorageLevel'].index,columns=inputs['sets']['t'])
        for t in ['HDAM','HPHS','BEVS','BATS','SCSP', 'P2GS']:
            temp = filter_by_tech(level,inputs,t)
            levels[t] = temp.sum(axis=1)
        levels.dropna(axis=1, inplace=True)
        for col in levels.columns:
            if levels[col].max() == 0 and levels[col].min() == 0:
                del levels[col]
        if aggregation is True:
            level = level.sum(axis=1)
        else:
            level = levels
    else:
        level = pd.Series(0, index=results['OutputPower'].index)

    if 'OutputPowerConsumption' in results:
        demand_p2h = filter_by_zone(results['OutputPowerConsumption'], inputs, z) / 1000  # GW
        demand_p2h = demand_p2h.sum(axis=1)
    else:
        demand_p2h = pd.Series(0, index=results['OutputPower'].index)
    if ('Flex', z) in inputs['param_df']['Demand']:
        demand_flex = inputs['param_df']['Demand'][('Flex', z)] / 1000
    else:
        demand_flex = pd.Series(0, index=results['OutputPower'].index)

    demand_da = inputs['param_df']['Demand'][('DA', z)] / 1000  # GW
    demand = pd.DataFrame(demand_da + demand_p2h + demand_flex, columns=[('DA', z)])
    demand = demand[('DA', z)]

    sum_generation = plotdata.sum(axis=1)
    # if 'OutputShedLoad' in results:
    if 'OutputShedLoad' in results and z in results['OutputShedLoad']:
        shed_load = results['OutputShedLoad'][z] / 1000  # GW
        shed_load = pd.Series(shed_load, index=demand.index).fillna(0)
    else:
        shed_load = pd.Series(0, index=demand.index) / 1000  # GW
    if 'OutputDemandModulation' in results and z in results['OutputDemandModulation']:
        shifted_load = -results['OutputDemandModulation'][z] / 1000  # GW
        shifted_load = pd.Series(shifted_load, index=demand.index).fillna(0)
    else:
        shifted_load = pd.Series(0, index=demand.index) / 1000  # GW
    diff = (sum_generation - demand + shifted_load + shed_load).abs()

    if diff.max() > 0.01 * demand.max():
        logging.critical('There is up to ' + str(
            diff.max() / demand.max() * 100) + '% difference in the instantaneous energy balance of zone ' + z)

    if 'OutputCurtailedPower' in results and z in results['OutputCurtailedPower']:
        curtailment = results['OutputCurtailedPower'][z] / 1000  # GW
    else:
        curtailment = None

    plot_dispatch(demand, plotdata, level, curtailment=curtailment, shedload=shed_load, shiftedload=shifted_load,
                  rng=rng, alpha=0.5)

    # Generation plot:
    if rug_plot:
        ZoneGeneration = filter_by_zone(results['OutputPower'], inputs, z)
        try:
            import enlopy as el  # try to get latest version
            el.plot_rug(ZoneGeneration, on_off=False, cmap='gist_heat_r', fig_title=z)
        except ImportError:
            plot_rug(ZoneGeneration, on_off=False, cmap='gist_heat_r', fig_title=z)

    return True


def storage_levels(inputs, results):
    """
    Reads the DispaSET results and provides the difference between the minimum storage profile and the computed storage profile

    :param inputs:      DispaSET inputs
    :param results:     DispaSET results
    """
    isstorage = pd.Series(index=inputs['units'].index)
    for u in isstorage.index:
        isstorage[u] = inputs['units'].Technology[u] in commons['tech_storage']
    sto_units = inputs['units'][isstorage]
    results['OutputStorageLevel'].plot(figsize=(12, 6), title='Storage levels')
    StorageError = ((inputs['param_df']['StorageProfile'] * sto_units.StorageCapacity).subtract(
        results['OutputStorageLevel'], 'columns')).divide((sto_units.StorageCapacity), 'columns') * (-100)
    StorageError = StorageError.dropna(1)
    if not StorageError.empty:
        ax = StorageError.plot(figsize=(12, 6),
                               title='Difference between the calculated storage Levels and the (imposed) minimum level')
        ax.set_ylabel('%')

    return True

    
def plot_storage_levels(inputs,results, z):
    """
    This function plots the reservoir levels profiles during the year
    #TODO: Check this function and decide if necessary
    :param inputs:      Dispa-SET inputs
    :param results:     Dispa-SET results
    :param z:           zone considered
    """
    BATS_unit = [ u for u in inputs['units'].index if (inputs['units'].loc[u,'Zone'] == z and inputs['units'].loc[u,'Technology'] == 'BATS')]
    H2_unit =  [ u for u in inputs['units'].index if inputs['units'].loc[u,'Zone'] == z and inputs['units'].loc[u,'Technology'] == 'P2GS']
    HDAM_unit = [ u for u in inputs['units'].index if inputs['units'].loc[u,'Zone'] == z and inputs['units'].loc[u,'Technology'] == 'HDAM']
        
    BATS_level = results['OutputStorageLevel'][BATS_unit]
    H2_level = results['OutputStorageLevel'][H2_unit]
    HDAM_level = results['OutputStorageLevel'][HDAM_unit]
    
    # plot
    index_plot = np.arange(len(BATS_level.index))
    plt.rcParams.update({'font.size': 10})
    fig, (ax, ax1, ax2) = plt.subplots(3, 1, sharex=True)
    #plt.rcParams.update({'font.size': 10})
    #for item in ([ax.title, ax.xaxis.label, ax.yaxis.label] +
    #         ax.get_xticklabels() + ax.get_yticklabels()):
    #    item.set_fontsize(10)
    ax.fill_between(index_plot,0, BATS_level.iloc[:,0], color = ('#41A317ff'))
    ax.set_ylabel('SOC - BATS [%]')
    ax.set_xlim(0, len(index_plot))

    ax1.fill_between(index_plot,0, H2_level.iloc[:,0], color = ('#A0522D'))
    ax1.set_ylabel('SOC - H2[%]')
    
    ax2.fill_between(index_plot,0, HDAM_level.iloc[:,0], color = ('#00a0e1ff'))
    ax2.set_ylabel('SOC - HDAM [%]')
    month_num = [360,1056, 1800, 2544, 3264, 4008, 4728, 5472, 6216, 6936, 7680, 8400]
    month_name = ['Jan', 'Feb', 'Mar', 'Apr','May', 'Jun', 'Jul',
                          'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    ax2.set_xticks(month_num)
    ax2.set_xticklabels(month_name)
    #plt.savefig('../../Manuscrit/figures/SOC_H2FLEX_UK.pdf',bbox_inches='tight' )
    
    return True

    
def plot_EFOH(inputs, results):
    """
    This function plots the equivalent full load operating hours of the electrolysers,
    together with the marginal price
    #TODO: Check this function and decide if necessary
    :param inputs:      Dispa-SET inputs
    :param results:     Dispa-SET results
    """
    EFOH = {}
    for i,s in enumerate(list(inputs.keys())):
        EFOH[i] = get_EFOH(inputs[s], results[s])
        EFOH[i] = EFOH[i].sort_values(by=['EFOH'], ascending=False)
    
    ind = np.arange(len(EFOH[0].index))
    labels = list(EFOH[0].index)
    for count, i in enumerate(labels):
        labels[count] = i.split()[2].split("_")[0]
        
    # mean_shadow = pd.DataFrame(index = labels, columns = ['cost'])
    # for i in mean_shadow.index:
    #     mean_shadow.loc[i,'cost'] = results_1['ShadowPrice'].loc[:,i].mean()
        
    x = np.arange(len(labels))  # the label locations
    width = 0.6/ len(list(inputs.keys())) # the width of the bars

    fig, ax = plt.subplots(figsize=(16,6))
    plt.rcParams.update({'font.size': 15})
    for item in ([ax.title, ax.xaxis.label, ax.yaxis.label] +
             ax.get_xticklabels() + ax.get_yticklabels()):
        item.set_fontsize(15)
    if len(list(inputs.keys())) == 2:
        ax.bar(x - width/2,EFOH[0].iloc[:,0] , width, label=list(inputs.keys())[0], color = (1, 0.5, 0, 1))
        ax.bar(x + width/2, EFOH[1].iloc[:,0], width, label=list(inputs.keys())[1], color = (0.192, 0.549, 0.905))
    elif len(list(inputs.keys())) == 3:
        ax.bar(x-0.2,EFOH[0].iloc[:,0] , width, label=list(inputs.keys())[0], color = (1, 0.5, 0, 1))
        ax.bar(x, EFOH[1].iloc[:,0], width, label=list(inputs.keys())[1], color = (0.192, 0.549, 0.905))
        ax.bar(x+0.2, EFOH[2].iloc[:,0], width, label=list(inputs.keys())[2], color = (0.192, 0.549, 0.3))

    # Add some text for labels, title and custom x-axis tick labels, etc.
    ax.set_ylabel('EFOH [h]')
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend()
    #plt.savefig('../../Manuscrit/figures/2_EFOH.pdf',bbox_inches='tight' )
    
    
    # fig, ax1 = plt.subplots(figsize=(13,5))

    # ax1.set_ylabel('EFOH [h]')
    # ax1.bar(ind, EFOH.iloc[:,0],0.3, color=(0.5, 0.5, 0.5, 1))
    # ax1.tick_params(axis='y')
    # ax1.grid(axis='y', linestyle='--')
    # ax1.set_xticks(ind)
    # ax1.set_xticklabels(label)
    #ax2 = ax1.twinx()  # instantiate a second axes that shares the same x-axis

    #ax2.set_ylabel('Average marginal price', color=(0.192, 0.549, 0.905))  # we already handled the x-label with ax1
    #ax2.plot(label, mean_shadow, color=(0.192, 0.549, 0.905))
    #ax2.tick_params(axis='y', labelcolor=(0.192, 0.449, 0.99))

    fig.tight_layout()  # otherwise the right y-label is slightly clipped
    return True

    
def plot_ElyserCap_vs_Utilization(inputs, results):
	#TODO: Check this function and decide if necesarry
    Data = pd.DataFrame(index =inputs['param_df']['sets']['n'], columns = ['Cap', 'Max'] )
    FC = pd.DataFrame(index =inputs['param_df']['sets']['n'], columns = [ 'FC'] )
    Sto = pd.DataFrame(index =inputs['param_df']['sets']['n'], columns = [ 'Sto'] ) 
    for u in inputs['param_df']['sets']['p2h2']:
        for z in inputs['param_df']['sets']['n']:
            if inputs['param_df']['Location'].loc[z,u]:
                Data.loc[z, 'Cap'] = inputs['param_df']['StorageChargingCapacity'].loc[u, 'StorageChargingCapacity']/1e3
                Data.loc[z,'Max'] = results['OutputStorageInput'].loc[:,u].max()/1e3
                FC.loc[z,'FC'] = inputs['param_df']['PowerCapacity'].loc[u, 'PowerCapacity']/1e3
                Sto.loc[z, 'Sto'] = inputs['param_df']['StorageCapacity'].loc[u, 'StorageCapacity']/1e3
                
    
    labels = Data.index
    x = np.arange(len(labels))  # the label locations
    width = 0.35 # the width of the bars
    ax = Data.loc[:,'Cap'].plot(kind="bar", figsize=(12, 8), stacked=True,
                                alpha=0.8, fontsize = 'medium')
    ax.set_ylabel('Capacity [GW]')
    ax.barh(Data.loc[:,'Max'], left=ax.get_xticks() - 0.4, width=0.8, height=ax.get_ylim()[1] * 0.005,
            linewidth=2,
            color='k')
    ax2 = FC.loc[:,'FC'].plot(kind="bar", figsize=(12, 8), stacked=True,
                                alpha=0.8, fontsize = 'medium')
    ax2.set_ylabel('Capacity [GW]')    
    
    ax3 = Sto.loc[:,'Sto'].plot(kind="bar", figsize=(12, 8), stacked=True,
                                alpha=0.8, fontsize = 'medium')
    ax3.set_ylabel('Capacity [GWh]')

    return True


    #TODO: Check this function adn decide if necessary
def plot_H2_and_demand(inputs, results):
    """
    This function plots the demand and the electrolyser demand as bar chart
    
    :param inputs:      Dispa-SET inputs
    :param results:     Dispa-SET results
    """
    # Get demand
    def get_demand(inputs, results):
        Demand = pd.DataFrame(index = ['0'], columns = inputs['sets']['n'])
        for z in inputs['sets']['n']:
            plotdata = get_plot_data(inputs, results, z) / 1000  # GW

            aggregation = False
            if 'OutputStorageLevel' in results:
                lev = filter_by_zone(results['OutputStorageLevel'], inputs, z)
                lev = lev * inputs['units']['StorageCapacity'].loc[lev.columns] / 1e3  # GWh of storage
                for col in lev.columns:
                    if 'BEVS' in col:
                        lev[col] = lev[col] * inputs['param_df']['AvailabilityFactor'][col]
                level = filter_by_storage(lev, inputs, StorageSubset='s')
                levels = pd.DataFrame(index=results['OutputStorageLevel'].index,columns=inputs['sets']['t'])
                for t in ['HDAM','HPHS','BEVS','BATS','SCSP', 'P2GS']:
                    temp = filter_by_tech(level,inputs,t)
                    levels[t] = temp.sum(axis=1)
                levels.dropna(axis=1, inplace=True)
                for col in levels.columns:
                    if levels[col].max() == 0 and levels[col].min() == 0:
                        del levels[col]
                if aggregation is True:
                    level = level.sum(axis=1)
                else:
                    level = levels
            else:
                level = pd.Series(0, index=results['OutputPower'].index)

            if 'OutputPowerConsumption' in results:
                demand_p2h = filter_by_zone(results['OutputPowerConsumption'], inputs, z) / 1e6  # TWh
                demand_p2h = demand_p2h.sum(axis=1)
            else:
                demand_p2h = pd.Series(0, index=results['OutputPower'].index)
            if ('Flex', z) in inputs['param_df']['Demand']:
                demand_flex = inputs['param_df']['Demand'][('Flex', z)] / 1e6
            else:
                demand_flex = pd.Series(0, index=results['OutputPower'].index)

            demand_da = inputs['param_df']['Demand'][('DA', z)] / 1e6  # TWh
            demand = pd.DataFrame(demand_da + demand_p2h + demand_flex, columns=[('DA', z)])
            demand = demand[('DA', z)]
            Demand[z] = demand.sum() 
        # Get elyser consumption
        Elyser_consumption = pd.DataFrame( index = ['0'], columns = inputs['sets']['n'])
        for u in results['OutputStorageInput'].columns:
            if 'P2GS' in u:
                c = u.split()[2].split('_')[0]
                Elyser_consumption[c] = results['OutputStorageInput'][u].sum()/1e6 #TWh
                Elyser_consumption[c].fillna(0)
        
        return Demand, Elyser_consumption
    
    Demand = {}
    Elyser_consumption = {}
    scenarios = list(inputs.keys())
    for s in scenarios:
        Demand[s] ,Elyser_consumption[s] = get_demand(inputs[s], results[s])
    
    labels = inputs[scenarios[0]]['sets']['n']
    
    x = np.arange(len(labels))  # the label locations
    if len(scenarios) == 2:
        width = 0.3
    else:
        width=0.2

    fig, ax = plt.subplots(figsize=(13,5))
    plt.rcParams.update({'font.size': 15})
    for item in ([ax.title, ax.xaxis.label, ax.yaxis.label] +
             ax.get_xticklabels() + ax.get_yticklabels()):
        item.set_fontsize(15)
    if len(scenarios) == 2:
        ax.bar(x - width/2 -0.03, Demand[scenarios[0]].iloc[0,:]+Elyser_consumption[scenarios[0]].iloc[0,:], width, color = (1, 0.5, 0, 0.7))
        ax.bar(x - width/2 -0.03, Demand[scenarios[0]].iloc[0,:], width, color = (1, 0.5, 0, 1), label=str(scenarios[0]))
        ax.bar(x + width/2 +0.03, Demand[scenarios[1]].iloc[0,:]+Elyser_consumption[scenarios[1]].iloc[0,:], width, color = (0.192, 0.549, 0.905, 0.7))
        ax.bar(x + width/2 +0.03, Demand[scenarios[1]].iloc[0,:], width, color = (0.192, 0.549, 0.905), label=str(scenarios[1]))
    elif len(scenarios) == 3:
        ax.bar(x - 0.22, Demand[scenarios[0]].iloc[0,:]+Elyser_consumption[scenarios[0]].iloc[0,:], width, label=str(scenarios[0]), color = (1, 0.5, 0, 0.7))
        ax.bar(x - 0.22, Demand[scenarios[0]].iloc[0,:], width, color = (1, 0.5, 0, 1))
        ax.bar(x , Demand[scenarios[1]].iloc[0,:]+Elyser_consumption[scenarios[1]].iloc[0,:], width, label=str(scenarios[1]), color = (0.192, 0.549, 0.905, 0.7))
        ax.bar(x , Demand[scenarios[1]].iloc[0,:], width, color = (0.192, 0.549, 0.905))
        ax.bar(x + 0.22, Demand[scenarios[2]].iloc[0,:]+Elyser_consumption[scenarios[2]].iloc[0,:], width, label=str(scenarios[2]), color = (0.192, 0.549, 0.3, 0.7))
        ax.bar(x + 0.22, Demand[scenarios[2]].iloc[0,:], width, color = (0.192, 0.549, 0.3))
    
    # Add some text for labels, title and custom x-axis tick labels, etc.
    ax.set_ylabel('[GWh]')
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend()
    #plt.savefig('../../Manuscrit/figures/1_H2_and_Demand.pdf',bbox_inches='tight' )
    
    #fig1=plt.figure(1,figsize=(13,5))
    # ind = np.arange(len(inputs['sets']['n']))
    # p1 = plt.bar(ind, Demand.iloc[0,:]+Elyser_consumption.iloc[0,:], 0.3, color=(0.5, 0.5, 0.5, 1))
    # p2 = plt.bar(ind, Elyser_consumption.iloc[0,:], 0.3, color=(1, 0.5, 0, 1))
    
    # plt.ylabel('[GWh]')
    # plt.xticks(ind, inputs['sets']['n'])
    # plt.legend((p1[0], p2[0]), ('Demand', 'Elyser consumption'))
    # plt.rcParams.update({'font.size': 11})
    # plt.rc('xtick', labelsize=10)
    return True

def plot_compare_costs(inputs_1, results_1, inputs_2, results_2):
    """
    This function plots bar charts to compare costs components between scenarios
    #TODO: Check this function
    :param inputs:      list of Dispa-SET inputs
    :param results:     list Dispa-SET results
    """    

    pkl_file = r"C:\Users\Eva\Downloads\MASTER\TFE\Dispa-SET\Simulations\JRC_EU_TIMES\NearZeroCarbon\ALLFLEX/ALLFLEX_costs.p"
    with open(pkl_file, "rb") as f:
        costs_1 = pickle.load(f)
    pkl_file = r"C:\Users\Eva\Downloads\MASTER\TFE\Dispa-SET\Simulations\JRC_EU_TIMES\NearZeroCarbon\NOCO2/NOCO2_costs.p"
    with open(pkl_file, "rb") as f:
        costs_2 = pickle.load(f)  
    
    Cost_1 = costs_1.sum()
    Cost_1 = Cost_1/1e6 #M€
    Cost_2 = costs_2.sum()
    Cost_2 = Cost_2/1e6
        
    for i in Cost_1.index:
        if Cost_1[i] == 0:
            if Cost_2[i] == 0:
                Cost_1.drop(i, inplace=True)
                Cost_2.drop(i, inplace=True)
            
            
    labels = ['CO2TAX_200', 'CO2TAX_0']

    x = [0,1]  # the label locations
    width = 0.35  # the width of the bars
    color = ['#566573', '#CCD1D1', '#85C1E9', '#F5B041', '#1D8348', '#0B5345', '#2471A3', '#5DADE2', '#AF7AC5']
    fig, ax = plt.subplots(figsize=(7,10))
    for i,c in enumerate(Cost_1.index):
        p1 = ax.bar(x[0] ,Cost_1[i:].sum()  , width, label=c, color = color[i])
        p2 = ax.bar(x[1] ,Cost_2[i:].sum() , width, color = color[i])
    # Add some text for labels, title and custom x-axis tick labels, etc.
    ax.set_ylabel('Cost [M€]')
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend()
        
    return True

#TODO: Check this function and decide if neccessary    
def plot_tech_cap(inputs):
    # # 1 plot production cap
    # Cap = pd.DataFrame(index = ['Elc sto', 'Elyser', 'FC', 'Hydro', 'NUC', 'Thermal', 
    #                             'Solar', 'Wind', 'Other'], columns = ['Cap']).fillna(0)
    # for u in inputs['param_df']['sets']['u']:
    #     if inputs['param_df']['Fuel'].loc['GAS',u] or inputs['param_df']['Fuel'].loc['OIL',u]:
    #         Cap.loc['Thermal', 'Cap'] += inputs['param_df']['PowerCapacity'].loc[u, 'PowerCapacity']
    #     elif inputs['param_df']['Fuel'].loc['LIG',u]:
    #         Cap.loc['Thermal', 'Cap'] += inputs['param_df']['PowerCapacity'].loc[u, 'PowerCapacity']
    #     elif inputs['param_df']['Fuel'].loc['HRD',u] or inputs['param_df']['Fuel'].loc['PEA',u]:
    #         Cap.loc['Thermal', 'Cap'] += inputs['param_df']['PowerCapacity'].loc[u, 'PowerCapacity']
    #     elif inputs['param_df']['Fuel'].loc['NUC',u]:
    #         Cap.loc['NUC', 'Cap'] += inputs['param_df']['PowerCapacity'].loc[u, 'PowerCapacity']
    #     elif inputs['param_df']['Technology'].loc['BATS',u]:
    #         Cap.loc['Elc sto', 'Cap'] += inputs['param_df']['PowerCapacity'].loc[u, 'PowerCapacity']
    #     elif inputs['param_df']['Technology'].loc['BEVS',u]:
    #         Cap.loc['Elc sto', 'Cap'] += inputs['param_df']['PowerCapacity'].loc[u, 'PowerCapacity']
    #     elif inputs['param_df']['Fuel'].loc['HYD',u]:
    #         Cap.loc['FC', 'Cap'] += inputs['param_df']['PowerCapacity'].loc[u, 'PowerCapacity']
    #         Cap.loc['Elyser', 'Cap'] += inputs['param_df']['StorageChargingCapacity'].loc[u, 'StorageChargingCapacity']
    #     elif inputs['param_df']['Fuel'].loc['WAT',u]:
    #         Cap.loc['Hydro', 'Cap'] += inputs['param_df']['PowerCapacity'].loc[u, 'PowerCapacity']
    #     elif inputs['param_df']['Fuel'].loc['WIN',u]:
    #         Cap.loc['Wind', 'Cap'] += inputs['param_df']['PowerCapacity'].loc[u, 'PowerCapacity']
    #     elif inputs['param_df']['Fuel'].loc['SUN',u]:
    #         Cap.loc['Solar', 'Cap'] += inputs['param_df']['PowerCapacity'].loc[u, 'PowerCapacity']
    #     elif inputs['param_df']['Fuel'].loc['GEO',u] or inputs['param_df']['Fuel'].loc['BIO',u]:
    #         Cap.loc['Other', 'Cap'] += inputs['param_df']['PowerCapacity'].loc[u, 'PowerCapacity']
        
    # colors = ['#41A317ff', '#A0522D', '#b9c33799', '#0f056b', '#466eb4ff', '#d7642dff', '#e6a532ff',
    #          '#41afaaff', '#57D53B']
    
    # added_cap = 0
    # for zone in inputs['sets']['n']:
    #     cap_before = pd.read_csv(r"C:\Users\Eva\Downloads\MASTER\TFE\Dispa-SET\Database\NearZeroCarbon\PowerPlants - before increase cap/"+ zone + "/JRC_EU_TIMES_NearZeroCarbon_2050_ALLFLEX.csv", header = 0)
    #     cap_after = pd.read_csv(r"C:\Users\Eva\Downloads\MASTER\TFE\Dispa-SET\Database\NearZeroCarbon\PowerPlants/"+ zone + "/JRC_EU_TIMES_NearZeroCarbon_2050_ALLFLEX.csv", header = 0)
    #     unit = [i for i in cap_before.index if cap_before.loc[i, 'Unit'] == zone+'_COMC_GAS']
    #     if unit == []:
    #         unit = [i for i in cap_before.index if cap_before.loc[i, 'Unit'] == zone+'_COMC_CCS_GAS']
    #     Nunits = cap_before.loc[unit, 'Nunits']
    #     before = cap_before.loc[unit, 'PowerCapacity'] *Nunits
    #     after = cap_after.loc[unit, 'PowerCapacity']*Nunits
    #     addition = (after - before)
    #     added_cap += addition.values[0]

    # x = [i for i in range(len(Cap.index))] # the label locations
    # width = 0.35  # the width of the bars
    # fig, ax = plt.subplots(figsize=(12,8))
    # for i,c in enumerate(Cap.index):
    #     if c == 'Thermal':
    #         p1 = ax.bar(x[i] ,(Cap.loc['Thermal', 'Cap']+added_cap)/1000  , width, color = colors[i], hatch = '//')
    #         p2 = ax.bar(x[i] ,Cap.loc['Thermal', 'Cap']/1000 , width, color = colors[i])
    #     else:
    #         p3 = ax.bar(x[i] ,Cap.iloc[i,0]/1000  , width, color = colors[i])
    # # Add some text for labels, title and custom x-axis tick labels, etc.
    # ax.set_ylabel('Capacity [GW]')
    # ax.set_xticks(x)
    # ax.set_xticklabels(Cap.index)
    # ax.grid(axis='y', linestyle='--')
    # #plt.savefig('../../Manuscrit/figures/Bar_plot_Capacities_prod.pdf',bbox_inches='tight' )
    
    # 2 plot storage cap
    Cap = pd.DataFrame(columns = [ 'BEVS', 'H2', 'Hydro', 'Thermal', 'BATS'], index = inputs['sets']['n']).fillna(0)
    for i,u in enumerate(inputs['param_df']['StorageCapacity'].index):
        for z in inputs['sets']['n']:
            if inputs['param_df']['Location'].loc[z,u]:
                if inputs['param_df']['Fuel'].loc['WAT',u] :
                    Cap.loc[z,'Hydro'] += inputs['param_df']['StorageCapacity'].fillna(0).iloc[i,0]*inputs['param_df']['Nunits'].iloc[i,0]
                elif inputs['param_df']['Fuel'].loc['HYD',u]:
                    Cap.loc[z,'H2'] += inputs['param_df']['StorageCapacity'].fillna(0).iloc[i,0]*inputs['param_df']['Nunits'].iloc[i,0]
                elif inputs['param_df']['Technology'].loc['BEVS',u]:
                    Cap.loc[z,'BEVS'] += inputs['param_df']['StorageCapacity'].fillna(0).iloc[i,0]*inputs['param_df']['Nunits'].iloc[i,0]
                elif inputs['param_df']['Technology'].loc['BATS',u]:
                    Cap.loc[z,'BATS'] += inputs['param_df']['StorageCapacity'].fillna(0).iloc[i,0]*inputs['param_df']['Nunits'].iloc[i,0]
                elif u in inputs['param_df']['sets']['p2h'] or u in inputs['param_df']['sets']['chp'] or inputs['param_df']['Technology'].loc['SCSP',u]:
                    Cap.loc[z,'Thermal'] += inputs['param_df']['StorageCapacity'].fillna(0).iloc[i,0]*inputs['param_df']['Nunits'].iloc[i,0]
    
    Cap = Cap/1000
    x = [i for i in range(len(Cap.index))] # the label locations
    width = 0.35  # the width of the bars
    colors = ['#57D53B', '#A0522D', '#00a0e1ff', '#C04000ff', 'black']
    fig, ax = plt.subplots(figsize=(12,8))
    
    
    ax = Cap.plot(kind="bar", figsize=(12, 8), stacked=True, color=colors,
                                alpha=0.8, legend='reverse')
    ax.set_ylabel('Capacity [GWh]')    
    
    
    # for i,c in enumerate(Cap.index):
    #     p3 = ax.bar(x[i] ,Cap.iloc[i,0]/1000  , width, color = colors[i])
    #     if c == 'Hydro':
    #         ax.text(i-0.15, Cap.iloc[i,0]/1000 +3000, str(int(round(Cap.iloc[i,0]/1000, 0))),va = 'center', color = colors[i], fontweight='bold')
    #     else:
    #         ax.text(i-0.1, Cap.iloc[i,0]/1000 +3000, str(int(round(Cap.iloc[i,0]/1000, 0))),va = 'center', color = colors[i], fontweight='bold')
    # # Add some text for labels, title and custom x-axis tick labels, etc.
    # ax.set_ylabel('Storage capacity [GWh]')
    # ax.set_xticks(x)
    # ax.set_xticklabels(Cap.index)
    # ax.grid(axis='y', linestyle='--')  
    #plt.savefig('../../Manuscrit/figures/Bar_plot_Capacities_sto.png',bbox_inches='tight' )        
    return True
def H2_demand_satisfaction(inputs, results):
    H2Demand = [0]
    OutputH2 = [0]
    for i in range(len(inputs.keys()) -1):
        H2Demand.append(0)
        OutputH2.append(0)
    for i,s in enumerate(list(inputs.keys())):
        for u in inputs[s]['param_df']['sets']['p2h2']:
            H2Demand[i] += (inputs[s]['param_df']['H2Demand'].loc[:,u].sum()
                           + inputs[s]['param_df']['PtLDemandInput'].loc[:,u].sum())
            OutputH2[i] += results[s]['OutputH2Output'].loc[:,u].sum()
    
    labels = list(inputs.keys())
    x = [i for i in range(len(labels))] # the label locations
    width = 0.2  # the width of the bars
    colors = ['#41afaaff']
    fig, ax = plt.subplots(figsize=(3*len(labels),6))
    for i,s in enumerate(list(inputs.keys())):
        if i==0:
            ax.bar(x[i] ,H2Demand[i]/1e6 , width, color = colors, hatch = '//', label = 'H2 slack')
            ax.bar(x[i] ,OutputH2[i]/1e6 , width, color = colors, label = 'H2 produced by elysers')
        else:
            ax.bar(x[i] ,H2Demand[i]/1e6 , width, color = colors, hatch = '//')
            ax.bar(x[i] ,OutputH2[i]/1e6 , width, color = colors)
   
    # Add some text for labels, title and custom x-axis tick labels, etc.
    ax.set_ylabel('H2 demand [TWh]')
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.grid(axis='y', linestyle='--')  
    ax.legend(loc='upper center', bbox_to_anchor=(0.5, 1.1),
          ncol=2)
    #plt.savefig('../../Manuscrit/figures/2_H2Demand.pdf',bbox_inches='tight' )
    return True
    
        

def heatmap(data, row_labels, col_labels, ax=None, cbar_kw={}, cbarlabel="", **kwargs):
    """
    Create a heatmap from a numpy array and two lists of labels.
    https://matplotlib.org/3.3.1/gallery/images_contours_and_fields/image_annotated_heatmap.html

    :param data:        A 2D numpy array of shape (N, M).
    :param row_labels:  A list or array of length N with the labels for the rows.
    :param col_labels:  A list or array of length M with the labels for the columns.
    :param ax:          A `matplotlib.axes.Axes`instance to which the heatmap is plotted. If not provided, use current axes or create a new one.  Optional.
    :param cbar_kw:     A dictionary with arguments to `matplotlib.Figure.colorbar`.  Optional.
    :param cbarlabel:   The label for the colorbar.  Optional.
    :param **kwargs:    All other arguments are forwarded to `imshow`.
    """

    if not ax:
        ax = plt.gca()

    # Plot the heatmap
    im = ax.imshow(data, **kwargs)

    # Create colorbar
    cbar = ax.figure.colorbar(im, ax=ax, **cbar_kw)
    cbar.ax.set_ylabel(cbarlabel, rotation=-90, va="bottom")

    # We want to show all ticks...
    ax.set_xticks(np.arange(data.shape[1]))
    ax.set_yticks(np.arange(data.shape[0]))
    # ... and label them with the respective list entries.
    ax.set_xticklabels(col_labels)
    ax.set_yticklabels(row_labels)

    # Let the horizontal axes labeling appear on top.
    ax.tick_params(top=True, bottom=False, labeltop=True, labelbottom=False)

    # Rotate the tick labels and set their alignment.
    plt.setp(ax.get_xticklabels(), rotation=0, ha="right", rotation_mode="anchor")

    # Turn spines off and create white grid.
    for edge, spine in ax.spines.items():
        spine.set_visible(False)

    ax.set_xticks(np.arange(data.shape[1] + 1) - .5, minor=True)
    ax.set_yticks(np.arange(data.shape[0] + 1) - .5, minor=True)
    ax.grid(which="minor", color="w", linestyle='-', linewidth=3)
    ax.tick_params(which="minor", bottom=False, left=False)
    ax.set_title('Power Flow Tracing Matrix')
    ax.set_ylabel('Supplied zones')
    ax.set_xlabel('Power Generating zones')

    return im, cbar


def annotate_heatmap(im, data=None, valfmt="{x:.2f}", textcolors=("black", "white"), threshold=None, **textkw):
    """
    A function to annotate a heatmap.
    https://matplotlib.org/3.3.1/gallery/images_contours_and_fields/image_annotated_heatmap.html
    :param im:          The AxesImage to be labeled.
    :param data:        Data used to annotate.  If None, the image's data is used.  Optional.
    :param valfmt:      The format of the annotations inside the heatmap. This should either use the string format
                        method, e.g. "$ {x:.2f}", or be a `matplotlib.ticker.Formatter`.  Optional.
    :param textcolors:  A pair of colors.  The first is used for values below a threshold, the second for those above.
                        Optional.
    :param threshold:   Value in data units according to which the colors from textcolors are applied.
                        If None (the default) uses the middle of the colormap as separation.  Optional.
    :param **kwargs:    All other arguments are forwarded to each call to `text` used to create the text labels.
    """

    if not isinstance(data, (list, np.ndarray)):
        data = im.get_array()

    # Normalize the threshold to the images color range.
    if threshold is not None:
        threshold = im.norm(threshold)
    else:
        threshold = im.norm(data.max()) / 2.

    # Set default alignment to center, but allow it to be
    # overwritten by textkw.
    kw = dict(horizontalalignment="center",
              verticalalignment="center")
    kw.update(textkw)

    # Get the formatter in case a string is supplied
    if isinstance(valfmt, str):
        valfmt = matplotlib.ticker.StrMethodFormatter(valfmt)

    # Loop over the data and create a `Text` for each "pixel".
    # Change the text's color depending on the data.
    texts = []
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            kw.update(color=textcolors[int(im.norm(data[i, j]) > threshold)])
            text = im.axes.text(j, i, valfmt(data[i, j], None), **kw)
            texts.append(text)

    return texts


def plot_power_flow_tracing_matrix(inputs, results, idx=None, figsize=(10, 7), **kwargs):
    """
    Plot power flow tracing matrix
    :param inputs:      Dispa-SET inputs
    :param results:     Dispa-SET results
    :param idx:         datetime index, a range of dates to analyze. By default it looks only at the first day of the
                        optimization. Optional.
    :param figsize:     Figure size. Optional.
    :param kwargs:
    :return:            Power flow tracing in MW and as a % of the total load in a particular region
    """
    data, data_prct = get_power_flow_tracing(inputs, results, idx)
    fig, ax = plt.subplots(figsize=figsize)
    im, cbar = heatmap(data_prct.values, data_prct.index, data_prct.columns,
                       cbarlabel="% of the total demand linked to one zone", **kwargs)
    texts = annotate_heatmap(im, valfmt="{x:.1f}")
    fig.tight_layout()
    plt.show()

    return data, data_prct


# Insipired by Pypsa geo plot
def get_projection_from_crs(crs):
    """
    EPSG coordinate system, 4326 is the default horizontal component of 3D system. Used by the GPS satellite navigation
    system and for NATO military geodetic surveying.

    :param crs:     EPSG:4326 (WGS84 Bounds:        -180.0000, -90.0000, 180.0000, 90.0000,
                               Projected Bounds:    -180.0000, -90.0000, 180.0000, 90.0000,
                               Area:                World)
    :return:        map projection
    """
    # if data is in lat-lon system, return default map with lat-lon system
    if crs == 4326:
        return ccrs.PlateCarree()
    try:
        return ccrs.epsg(crs)
    except requests.RequestException:
        logging.warning("A connection to http://epsg.io/ is required for a projected coordinate reference system. "
                        "Falling back to lat-long.")
    except ValueError:
        logging.warning("'{crs}' does not define a projected coordinate system. "
                        "Falling back to lat-long.".format(crs=crs))
        return ccrs.PlateCarree()


def compute_bbox_with_margins(x, y, margin_type='Fixed', margin=0):
    """
    'Helper function to compute bounding box for the plot'

    :param margin:  how much percent is box beyond the ploted network
    :param x:       latitude
    :param y:       longitude
    :return:        tuples of 2 coordinates (min, max)
    """
    # set margins
    pos = np.asarray((x, y))
    minxy, maxxy = pos.min(axis=1), pos.max(axis=1)
    if margin_type == 'Fixed':
        xy1 = minxy - margin
        xy2 = maxxy + margin
    else:
        xy1 = minxy - margin * (maxxy - minxy)
        xy2 = maxxy + margin * (maxxy - minxy)

    return tuple(xy1), tuple(xy2)


#TODO: Check this function and provide descriptions
def draw_map_cartopy(x, y, ax, crs=4326, boundaries=None, margin_type='Fixed', margin=0.05, geomap=True,
                     color_geomap=None, terrain=False):
    if boundaries is None:
        (x1, y1), (x2, y2) = compute_bbox_with_margins(x, y, margin_type, margin)
    else:
        x1, x2, y1, y2 = boundaries

    resolution = '50m' if isinstance(geomap, bool) else geomap
    assert resolution in ['10m', '50m', '110m'], ("Resolution has to be one of '10m', '50m', '110m'")
    axis_transformation = get_projection_from_crs(crs)
    ax.set_extent([x1, x2, y1, y2], crs=axis_transformation)

    if color_geomap is None:
        color_geomap = {'ocean': 'w', 'land': 'w'}
    elif color_geomap and not isinstance(color_geomap, dict):
        color_geomap = {'ocean': 'lightblue', 'land': 'whitesmoke'}

    ax.add_feature(cartopy.feature.LAND.with_scale(resolution), facecolor=color_geomap['land'])
    ax.add_feature(cartopy.feature.OCEAN.with_scale(resolution), facecolor=color_geomap['ocean'])

    ax.coastlines(linewidth=1, zorder=2, resolution=resolution)
    border = cartopy.feature.BORDERS.with_scale(resolution)
    ax.add_feature(border, linewidth=0.8)

    if terrain is True:
        # Create a Stamen terrain background instance.
        stamen_terrain = cimgt.Stamen('terrain-background')
        # Add the Stamen data at zoom level 8.
        ax.add_image(stamen_terrain, 8)

    return axis_transformation


#TODO: Check this function and provide descriptions    
def get_congestion(inputs, flows, idx):
    cols = [ x for x in inputs['sets']['l'] if "RoW" not in x ]
    cgst = pd.DataFrame(columns=cols)
    for l in flows:
        if l[:3] != 'RoW' and l[-3:] != 'RoW':
            cgst.loc[0, l] = (
                (flows.loc[idx, l] == inputs['param_df']['FlowMaximum'].loc[idx, l]) & (
                 inputs['param_df']['FlowMaximum'].loc[idx, l] > 0)).sum()

    cgst.fillna(0, inplace=True)
    cgst = cgst / inputs['param_df']['Demand'].loc[idx, :].index.size
    return cgst


#TODO: Generalize this function and provide descriptions    
def plot_net_flows_map(inputs, results, idx=None, crs=4326, boundaries=None, margin_type='Fixed', margin=0.20,
                       geomap=True, color_geomap=None, terrain=False, figsize=(12,8)):

    # Preprocess input data
    flows = results['OutputFlow'].copy()
    zones = inputs['sets']['n'].copy()
    geo = inputs['geo'].copy()

    # Checking if index was selected
    if idx is None:
        idx = inputs['param_df']['Demand'].index
        logging.info('No datetime range specified, net flows map is printed for the entire optimization')
    else:
        idx = idx

    Flows = get_from_to_flows(inputs, flows, zones, idx)
    NetImports, P = get_net_positions(inputs, results, zones, idx)

    # Scale net position of the zone TODO: maybe apply some other algorithm instead of scaling based on the highest net position
    P = P / P.max()

    # Create a directed graph
    g = nx.DiGraph()
    # Add zones
    g.add_nodes_from(zones)
    # Define and add edges
    edges = Flows[['From', 'To']].values
    g.add_edges_from(edges)
    # Assign weights (between 0 - 10 seems quite reasonable), weights are sized according to the highest one
    # TODO: Not sure if this is somethign we are after, maybe there should be another method used for scaling i.e. based on max NTC
    weights = (10 * Flows['Flow'] / Flows['Flow'].max()).values

    # Define geospatial coordinates
    pos = {zone: (v['CapitalLongitude'], v['CapitalLatitude']) for zone, v in geo.to_dict('index').items()}

    # Node sizes (Based on the net position of a zone)
    sizes = [5000 * P[i] for i in g.nodes]

    # Assign colors based on net flows (if importing/exporting/neutral)
    node_neg = NetImports.columns[(NetImports < 0).any()].tolist()
    node_pos = NetImports.columns[(NetImports >= 0).any()].tolist()
    color_map = []
    for node in g:
        if node in node_neg:
            color_map.append('green')
        elif node in node_pos:
            color_map.append('red')
        else:
            color_map.append('blue')

    # Show labels only in nodes whose size is > 100
    labels = {i: i if 5000 * P[i] >= 100 else '' for i in g.nodes}

    # Define projection (FIXME: currently only 4326 possible)
    projection = get_projection_from_crs(4326)

    # Create figure
    fig, ax = plt.subplots(1, 1, figsize=figsize, subplot_kw=dict(projection=projection))
    title = "Power feed (red=Imports, green=Exports, blue=Neutral)"

    # Assign geo coordinates and draw them on a map
    x, y = geo['CapitalLongitude'], geo['CapitalLatitude']
    transform = draw_map_cartopy(x, y, ax, crs, boundaries, margin_type, margin, geomap, color_geomap, terrain)
    x, y, z = ax.projection.transform_points(transform, x.values, y.values).T

    x, y = pd.Series(x, geo.index), pd.Series(y, geo.index)

    # Draw networkx graph with nodes and edges
    nx.draw_networkx(g, ax=ax, font_size=16,
                     # alpha=.7,
                     width=weights,
                     node_size=sizes,
                     labels=labels,
                     pos=pos,
                     node_color=color_map,
                     cmap=plt.cm.autumn,
                     arrows=True, arrowstyle='-|>', arrowsize=20, connectionstyle='arc3, rad=0.1',
                     )

    ax.update_datalim(compute_bbox_with_margins(x, y, margin_type, margin))
    ax.autoscale_view()

    if geomap:
        ax.outline_patch.set_visible(False)
    else:
        ax.set_aspect('equal')
    ax.axis('off')
    ax.set_title(title)

    plt.show()

#TODO: Generalize this function and provide descriptions
def plot_line_congestion_map(inputs, results, idx=None, crs=4326, boundaries=None, margin_type='Fixed', margin=0.20,
                             geomap=True, color_geomap=None, terrain=False, figsize=(12,8), edge_width=10):

    # # Testing
    # crs = 4326
    # boundaries = None
    # margin_type = 'Fixed'
    # margin = 5.5
    # geomap = True
    # color_geomap = None
    # terrain = False
    # figsize = (12, 8)

    # Preprocess input data
    zones = inputs['sets']['n'].copy()
    geo = inputs['geo'].copy()
    flows = results['OutputFlow'].copy()

    # Checking if index was selected
    if idx is None:
        idx = inputs['param_df']['Demand'].index
        logging.info('No datetime range specified, net flows map is printed for the entire optimization')
    else:
        idx = idx

    cgst = get_congestion(inputs, flows, idx)

    Congestion = get_from_to_flows(inputs, cgst, zones)

    # Create a directed graph
    g = nx.DiGraph()
    # Add zones
    g.add_nodes_from(zones)
    # Define and add edges
    edges = Congestion[['From', 'To']].values
    g.add_edges_from(edges)
    # Assign weights (between 0 - 10 seems quite reasonable), weights are sized according to the highest one
    # TODO: Not sure if this is somethign we are after, maybe there should be another method used for scaling i.e. based on max NTC
    weights = (100*Congestion['Flow']).values

    # Define geospatial coordinates
    pos = {zone: (v['CapitalLongitude'], v['CapitalLatitude']) for zone, v in geo.to_dict('index').items()}

    # Node sizes (Based on the net position of a zone)
    sizes = [3000 for i in g.nodes]

    # Show labels only in nodes whose size is > 100
    labels = {i: i for i in g.nodes}

    # Define projection (FIXME: currently only 4326 possible)
    projection = get_projection_from_crs(4326)

    # Create figure
    fig, ax = plt.subplots(1, 1, figsize=figsize, subplot_kw=dict(projection=projection))
    title = "Line Congestion (Congestion levels: dark_red=High, green=Middle, blue=None)"

    # Assign geo coordinates and draw them on a map
    x, y = geo['CapitalLongitude'], geo['CapitalLatitude']
    transform = draw_map_cartopy(x, y, ax, crs, boundaries, margin_type, margin, geomap, color_geomap, terrain)
    x, y, z = ax.projection.transform_points(transform, x.values, y.values).T

    x, y = pd.Series(x, geo.index), pd.Series(y, geo.index)

    edge_cmap = plt.cm.jet
    edge_vmin = 0.0
    edge_vmax = 100
    cmap = plt.cm.autumn

    # Draw networkx graph with nodes and edges
    nx.draw_networkx(g, ax=ax, font_size=18,
                     # alpha=.7,
                     width=edge_width,
                     node_size=sizes,
                     labels=labels,
                     pos=pos,
                     edge_color=weights,
                     edge_cmap=edge_cmap,
                     cmap=cmap,
                     arrows=True, arrowstyle='-|>', arrowsize=20, connectionstyle='arc3, rad=0.1',
                     edge_vmin=edge_vmin, edge_vmax=edge_vmax
                     )

    sm = plt.cm.ScalarMappable(cmap=edge_cmap, norm=plt.Normalize(vmin=edge_vmin, vmax=edge_vmax))
    sm.set_array([])
    cbar = plt.colorbar(sm)

    ax.update_datalim(compute_bbox_with_margins(x, y, margin_type, margin))
    ax.autoscale_view()

    if geomap:
        ax.outline_patch.set_visible(False)
    else:
        ax.set_aspect('equal')
    ax.axis('off')
    ax.set_title(title)

    plt.show()
