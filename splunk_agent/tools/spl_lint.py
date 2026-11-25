"""A simple SPL checker. It does not need a Splunk server.

lint_spl(query) returns:
    {"valid": bool, "errors": [str], "warnings": [str]}

Errors are things Splunk would reject. Warnings are performance or style problems.
"""

import re

KNOWN_COMMANDS = set("""
addcoltotals addinfo addtotals append appendcols appendpipe bin bucket chart cluster collect
convert datamodel dbxquery dedup delta eval eventcount eventstats extract fieldformat fields
fieldsummary filldown fillnull foreach format from gentimes geostats head inputcsv inputlookup
iplocation join kmeans kv loadjob lookup makemv makeresults map metadata metasearch mstats
multisearch mvcombine mvexpand nomv outlier outputcsv outputlookup pivot predict rangemap rare
regex rename replace rest return reverse rex savedsearch search sendemail set sort spath stats
streamstats table tags tail timechart timewrap top transaction transpose trendline tstats union
untable where xmlkv xpath xyseries
""".split())

# These commands create results, so they must come first: "| tstats ...".
GENERATING_COMMANDS = set("""
tstats inputlookup makeresults rest datamodel metadata from pivot mstats dbxquery inputcsv
loadjob savedsearch eventcount gentimes metasearch multisearch union
""".split())


def split_pipeline(spl: str) -> tuple[list[str], list[str]]:
    """Split a query on top-level pipes. Pipes inside quotes, () or [] are ignored.

    Returns (stages, errors) where errors are unbalanced quotes/brackets.
    """
    stages, errors = [], []
    current = ""
    open_brackets = []  # stack of "(" and "["
    in_quotes = False
    i = 0
    while i < len(spl):
        ch = spl[i]
        if in_quotes:
            if ch == "\\":  # escaped character, keep both
                current += spl[i : i + 2]
                i += 2
                continue
            if ch == '"':
                in_quotes = False
        elif ch == '"':
            in_quotes = True
        elif ch in "([":
            open_brackets.append(ch)
        elif ch in ")]":
            expected = "(" if ch == ")" else "["
            if open_brackets and open_brackets[-1] == expected:
                open_brackets.pop()
            else:
                errors.append(f"Unexpected '{ch}' (no matching '{expected}').")
        elif ch == "|" and not open_brackets:
            stages.append(current)
            current = ""
            i += 1
            continue
        current += ch
        i += 1
    stages.append(current)

    if in_quotes:
        errors.append("Unbalanced quotes: a double-quoted string is never closed.")
    for bracket in open_brackets:
        errors.append(f"Unbalanced brackets: '{bracket}' is never closed.")
    return stages, errors


def first_word(text: str) -> str:
    match = re.match(r"\s*(\w+)", text)
    return match.group(1).lower() if match else ""


def lint_spl(spl: str, required_fields: list[str] | None = None) -> dict:
    spl = (spl or "").strip()
    if not spl:
        return {"valid": False, "errors": ["Query is empty."], "warnings": []}

    stages, errors = split_pipeline(spl)
    warnings = []

    starts_with_pipe = spl.startswith("|")
    if starts_with_pipe:
        stages = stages[1:]  # drop the empty text before the first "|"

    for position, stage in enumerate(stages, start=1):
        command = first_word(stage)

        if not stage.strip():
            errors.append(f"Stage {position} is empty (double '|' or a '|' at the end).")
            continue

        # The first stage without a leading pipe is an implicit "search".
        if position == 1 and not starts_with_pipe:
            if command in GENERATING_COMMANDS:
                errors.append(f"'{command}' must start with a pipe: '| {command} ...'.")
            continue

        if command not in KNOWN_COMMANDS:
            warnings.append(f"'{command}' is not a built-in command (typo or custom command?).")
        if command in GENERATING_COMMANDS and position > 1 and not re.search(r"append\s*=\s*t", stage, re.I):
            errors.append(f"'{command}' must be the first command in the query.")
        if command in ("stats", "eventstats", "streamstats", "chart", "timechart") and re.search(r"\bby\s*$", stage, re.I):
            errors.append(f"'{command} ... by' is missing the field to group by.")
        if command == "eval" and "=" not in stage:
            errors.append("'eval' needs an assignment like 'field=expression'.")
        if command == "rex" and '"' not in stage:
            errors.append("'rex' needs a regular expression in double quotes.")
        if command == "transaction":
            warnings.append("'transaction' is slow; prefer 'stats ... by <id field>'.")
        if command == "join":
            warnings.append("'join' is slow and limited to 50,000 rows; prefer 'stats' or 'lookup'.")

    if not starts_with_pipe:
        base_search = stages[0]
        if "index=" not in base_search.replace(" ", "") and "`" not in base_search:
            warnings.append("No 'index=' in the base search; it will scan all default indexes.")
        if re.search(r"index\s*=\s*\*", base_search):
            warnings.append("'index=*' scans every index; name the index.")

    missing = [f for f in (required_fields or []) if not re.search(rf"\b{re.escape(f)}\b", spl)]
    if missing:
        warnings.append(f"Missing required field(s): {', '.join(missing)}.")

    return {"valid": not errors, "errors": errors, "warnings": warnings}


def extract_spl_blocks(text: str) -> list[str]:
    """Return the contents of ```spl code blocks in a model answer."""
    blocks = re.findall(r"```(?:spl|splunk|sql)?\s*\n(.*?)```", text or "", re.S | re.I)
    return [b.strip() for b in blocks if b.strip()]
