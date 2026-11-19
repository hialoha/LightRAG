import sys
from unittest.mock import patch


def test_agent_format_preserves_source_and_positions():
    argv = sys.argv[:]
    try:
        sys.argv = [sys.argv[0]]
        with patch("dotenv.dotenv_values", return_value={}):
            from lightrag.api.routers.query_routes import _format_query_data_for_agent
    finally:
        sys.argv = argv
    from lightrag.utils import convert_to_user_format
    original = {"chunk_id":"c", "full_doc_id":"d", "content":"original evidence", "content_type":"text",
                "title":"Paper", "filename":"paper.pdf", "page_id":0, "chunk_order_index":4,
                "segment_order_index":5, "truncated":False}
    wire = _format_query_data_for_agent(convert_to_user_format([], [], [original], [], "naive"))
    chunk = wire["data"]["chunks"][0]
    for key in ("chunk_id","full_doc_id","title","filename","page_id","chunk_order_index","segment_order_index","truncated"):
        assert chunk[key] == original[key]
    assert chunk["image_text"] == original["content"]
