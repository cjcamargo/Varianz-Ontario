from __future__ import annotations

from dataclasses import dataclass


DEFINITIONS_VERSION = "2.2.0"
DATA_VERSION = "wageningen-reference-2020-v1"
MODEL_VERSION = "energy-baseline-2.1.0"


@dataclass(frozen=True)
class MetricDefinition:
    code: str
    label: str
    dimension: str
    unit: str
    grain: str
    aggregation: str
    source: str
    quality_rule: str


def metric(
    code: str,
    label: str,
    dimension: str,
    unit: str,
    grain: str = "5min",
    aggregation: str = "mean",
    source: str = "GreenhouseClimate",
    quality_rule: str = "finite",
) -> MetricDefinition:
    return MetricDefinition(
        code, label, dimension, unit, grain, aggregation, source, quality_rule
    )


METRICS = {
    item.code: item
    for item in [
        metric("Tair", "Greenhouse air temperature", "temperature", "degC"),
        metric("Rhair", "Greenhouse relative humidity", "relative_humidity", "%"),
        metric("HumDef", "Greenhouse humidity deficit", "humidity_deficit", "g/m3"),
        metric("CO2air", "Greenhouse carbon dioxide concentration", "concentration", "ppm"),
        metric("AssimLight", "HPS lamps status", "control_signal", "%", aggregation="max"),
        metric("EnScr", "Energy curtain opening", "control_signal", "%"),
        metric("VentLee", "Leeward vents opening", "control_signal", "%"),
        metric("Ventwind", "Windward vents opening", "control_signal", "%"),
        metric("PipeLow", "Rail pipe temperature", "temperature", "degC"),
        metric("PipeGrow", "Crop pipe temperature", "temperature", "degC"),
        metric("t_heat_vip", "Realized heating temperature setpoint", "temperature", "degC"),
        metric("t_ventlee_vip", "Realized leeward ventilation temperature setpoint", "temperature", "degC"),
        metric("co2_vip", "Realized carbon dioxide setpoint", "concentration", "ppm"),
        metric("dx_vip", "Realized humidity deficit setpoint", "humidity_deficit", "g/m3"),
        metric("scr_enrg_vip", "Realized energy curtain setpoint", "control_signal", "%"),
        metric("Cum_irr", "Cumulative daily irrigation", "water", "L/m2/day", aggregation="max"),
        metric("Tot_PAR", "Total inside PAR", "irradiance", "umol/m2/s"),
        metric("Tot_PAR_Lamps", "Lamp PAR contribution", "irradiance", "umol/m2/s"),
        metric("co2_dos", "Carbon dioxide dosing rate", "resource_rate", "kg/ha/hour"),
        metric("Tout", "Outdoor temperature", "temperature", "degC", source="Weather"),
        metric("Rhout", "Outdoor relative humidity", "relative_humidity", "%", source="Weather"),
        metric("Iglob", "Global solar radiation", "irradiance", "W/m2", source="Weather"),
        metric("Windsp", "Outdoor wind speed", "speed", "m/s", source="Weather"),
        metric("Heat_cons", "Heating energy consumption", "energy", "MJ/m2/day", "daily", "sum", "Resources"),
        metric("ElecHigh", "Peak-hours artificial-light electricity consumption", "electricity", "kWh/m2/day", "daily", "sum", "Resources"),
        metric("ElecLow", "Off-peak artificial-light electricity consumption", "electricity", "kWh/m2/day", "daily", "sum", "Resources"),
        metric("CO2_cons", "Carbon dioxide consumption", "resource", "kg/m2/day", "daily", "sum", "Resources"),
        metric("Irr", "Irrigation water", "water", "L/m2/day", "daily", "sum", "Resources"),
        metric("Drain", "Drain water", "water", "L/m2/day", "daily", "sum", "Resources"),
    ]
}


OPERATIONAL_CODES = tuple(code for code, item in METRICS.items() if item.grain == "5min")
RESOURCE_CODES = tuple(code for code, item in METRICS.items() if item.grain == "daily")
