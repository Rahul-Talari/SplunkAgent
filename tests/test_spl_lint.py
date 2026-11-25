from splunk_agent.tools import extract_spl_blocks, lint_spl, scrub_query


def errors(spl):
    return " ".join(lint_spl(spl)["errors"])


def warnings(spl, **kwargs):
    return " ".join(lint_spl(spl, **kwargs)["warnings"])


def test_valid_query():
    result = lint_spl("index=wineventlog EventCode=4625 | stats count by user, src | where count > 10")
    assert result == {"valid": True, "errors": [], "warnings": []}


def test_pipes_inside_quotes_and_brackets_are_ignored():
    assert lint_spl('index=web | rex field=uri "^/a|b/(?<x>\\w+)" | eval y=if(a=="|", 1, 0)')["valid"]


def test_unbalanced_quotes_and_brackets():
    assert "quotes" in errors('index=a | search user!="*$ | stats count')
    assert "brackets" in errors("index=a | eval x=if(a=1, 2, 3")
    assert "brackets" in errors("index=a [search index=b | fields user")


def test_empty_stage():
    assert "empty" in errors("index=a | | stats count")
    assert "empty" in errors("index=a | stats count |")


def test_generating_command_position():
    assert "first command" in errors("index=net | tstats count where index=net by src")
    assert "start with a pipe" in errors("tstats count where index=net by src")
    assert lint_spl("| tstats count where index=net by src")["valid"]
    assert lint_spl("| tstats count where index=a by src | tstats append=t count where index=b by src")["valid"]


def test_command_specific_errors():
    assert "group by" in errors("index=a | stats count by")
    assert "assignment" in errors("index=a | eval lower(user)")
    assert "regular expression" in errors("index=a | rex field=x")


def test_warnings():
    assert "not a built-in" in warnings("index=a | statz count")
    assert lint_spl("index=a | statz count")["valid"]  # warnings don't make it invalid
    assert "transaction" in warnings("index=a | transaction user")
    assert "No 'index='" in warnings("sourcetype=foo error")
    assert "index=*" in warnings("index=* error")
    assert "SAFE_name" in warnings("index=a | table Account", required_fields=["Account", "SAFE_name"])


def test_extract_spl_blocks():
    text = "Here:\n```spl\nindex=a | stats count\n```\nand\n```\n| makeresults\n```"
    assert extract_spl_blocks(text) == ["index=a | stats count", "| makeresults"]


def test_scrub_query_removes_sensitive_values():
    query = scrub_query("sshd failed password 203.0.113.50 jdoe@corp.com CORP\\jdoe")
    assert query == "sshd failed password"
