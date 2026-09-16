"""CST 2026 Optimizer VBA configuration; starting is always a separate action."""

from cst_mcp.validators import validate_name
from cst_mcp.vba_builder import VBABuilder


def build_optimizer(args: dict, kind: str = "single") -> str:
    methods = {
        "Trust Region": "Trust_Region",
        "Trust_Region": "Trust_Region",
        "Nelder Mead": "Nelder_Mead_Simplex",
        "Nelder_Mead_Simplex": "Nelder_Mead_Simplex",
        "CMAES": "CMAES",
    }
    method = methods.get(args.get("method", "CMAES" if kind == "multi" else "Trust Region"))
    if method is None:
        raise ValueError(
            "Evaluation-capped native optimization supports Trust Region, Nelder Mead, or CMAES. Other algorithms require an explicit iteration/population budget."
        )
    maximum = int(args.get("max_evaluations", 100))
    if maximum < 2:
        raise ValueError("max_evaluations must be at least 2")
    parameters = args.get("parameters", [])
    if not parameters:
        raise ValueError("At least one varying parameter is required")
    if kind == "single":
        goals = [dict(args, target_value=args.get("goal_value", 0))]
    elif kind == "multi":
        goals = args["goals"]
    else:
        goals = [args["objective"]]
    if not goals:
        raise ValueError("At least one goal is required")
    builder = (
        VBABuilder("Optimizer")
        .set("SetOptimizerType", method)
        .call_with_args("SetUseMaxEval", "True", method)
        .call_with_args("SetMaxEval", str(maximum), method)
        .call("InitParameterList")
        .call("ResetParameterList")
        .call("DeleteAllGoals")
        .set_bool("StartActiveSolver", True)
    )
    for parameter in parameters:
        name = validate_name(parameter["name"], "parameter")
        low, high = float(parameter["min"]), float(parameter["max"])
        if low >= high:
            raise ValueError("Parameter min must be below max")
        builder.call_with_args("SelectParameter", name, "True").set_number(
            "SetParameterMin", low
        ).set_number("SetParameterMax", high)
    combined = [(g, None) for g in goals] + [
        (c, c["operator"]) for c in args.get("constraints", [])
    ]
    for goal, constraint in combined:
        path = goal["result_path"]
        complex_result = "S-Parameters" in path
        builder.call_with_args(
            "AddGoal", "1DC Primary Result" if complex_result else "1D Primary Result"
        )
        builder.set("SetGoal1DCResultName" if complex_result else "SetGoal1DResultName", path)
        if complex_result:
            builder.set("SetGoalScalarType", "magdb20")
        operator = (
            {"minimize": "min", "maximize": "max", "target": "="}.get(goal.get("goal_type"))
            if constraint is None
            else {"<": "<", "<=": "<", ">": ">", ">=": ">", "=": "="}.get(constraint)
        )
        if not operator:
            raise ValueError("Unsupported goal operator")
        builder.set("SetGoalOperator", operator).set_number(
            "SetGoalWeight", float(goal.get("weight", 1))
        )
        if operator in {"<", ">", "="}:
            builder.set_number(
                "SetGoalTarget",
                float(goal.get("value", goal.get("target_value", goal.get("goal_value", 0)))),
            )
        if "frequency_ghz" in goal:
            frequency = float(goal["frequency_ghz"])
            builder.set("SetGoalRangeType", "single").set_double(
                "SetGoalRange", frequency, frequency
            )
        else:
            builder.set("SetGoalRangeType", "total")
    return "' Configuration only. Explicit Optimizer.Start is required to run.\n" + builder.build()
