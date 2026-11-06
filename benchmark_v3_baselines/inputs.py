"""Deterministic public input grids for the five pilot tasks.

The grids are derived by hand from the published ``legal_input_contract``
before seeing any result.  They are intentionally small and fixed so that
every baseline sees the same finite domain and the run is reproducible.
"""
from __future__ import annotations

from typing import Any, Dict, List

GRIDS: Dict[str, List[Dict[str, Any]]] = {
    "jinja2_bytecode_cache_read": [
        {"template": "{{ 6*7 }}"},
        {"template": "{{ 6*7 }}", "cached_source": "{{ 1+1 }}"},
        {"template": "hello {{ name }}", "cached_source": "{{ 1+1 }}",
         "context": {"name": "x"}},
        {"template": "{{ 1+1 }}"},
        {"template": "{% for i in [1,2] %}{{ i }}{% endfor %}"},
        {"template": "{{ 6*7 }}", "cached_source": "{{ 6*7 }}"},
    ],
    "werkzeug_bind_server_name_lower": [
        {"host": "example.com", "server_name": None, "subdomain": None},
        {"host": "example.com", "server_name": "EXAMPLE.COM", "subdomain": None},
        {"host": "example.com", "server_name": "EXAMPLE.COM", "subdomain": "www"},
        {"host": "sub.example.com", "server_name": "EXAMPLE.COM", "subdomain": None},
        {"host": "example.com", "server_name": "example.com:80", "subdomain": "www"},
        {"host": "example.com", "server_name": "EXAMPLE.COM:443", "subdomain": "www"},
        {"host": "EXAMPLE.COM", "server_name": None, "subdomain": "api"},
    ],
    "werkzeug_filestorage_stream_name": [
        {"stream": "tempfile"},
        {"stream": "stderr"},
        {"stream": "none", "data": "abc"},
        {"stream": "named", "data": "abc", "name": "x.txt"},
        {"stream": "named", "data": "abc", "name": "<stderr>"},
        {"stream": "named", "data": "abc", "name": "<stdin>"},
    ],
    "werkzeug_get_host_default_empty": [
        {"scheme": "http", "host_header": None, "server": None},
        {"scheme": "http", "host_header": "example.com", "server": None},
        {"scheme": "http", "host_header": None, "server": ["example.com", 8080]},
        {"scheme": "https", "host_header": "example.com:443", "server": ["example.com", 443]},
        {"scheme": "ws", "host_header": "Example.COM:80", "server": None},
        {"scheme": "http", "host_header": "spam", "server": ["spam", 80]},
        {"scheme": "wss", "host_header": None, "server": ["unix/socket", None]},
    ],
    "werkzeug_secure_filename_ascii_filter": [
        {"filename": "a b"},
        {"filename": "北京.txt"},
        {"filename": "My cool movie.mov"},
        {"filename": "../../../etc/passwd"},
        {"filename": "i contain cool ümläuts.txt"},
        {"filename": "CON"},
        {"filename": "a b"},
        {"filename": ""},
    ],
}


def grid_for(task_id: str, max_inputs: int | None = None) -> List[Dict[str, Any]]:
    items = [dict(item) for item in GRIDS[task_id]]
    if max_inputs is not None:
        items = items[:max_inputs]
    return items
