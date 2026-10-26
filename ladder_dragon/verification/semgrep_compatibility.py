# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify and install the isolated downstream static analyzer.
"""Exercise downstream dependency APIs without application imports or network access."""


def main():
    import asyncio
    import importlib.metadata as md
    import json
    import socket
    def reject(*a, **kw):
        raise AssertionError("network forbidden")
    socket.socket.connect = reject
    socket.create_connection = reject
    import semgrep.telemetry
    import semgrep.commands.mcp
    from mcp.server.fastmcp import FastMCP
    from semgrep.mcp.server import register
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.instrumentation.requests import RequestsInstrumentor
    from opentelemetry.instrumentation.threading import ThreadingInstrumentor
    import jwt
    server = FastMCP("local-compatibility-check")
    register(server)
    tools = asyncio.run(server.list_tools())
    assert len(tools) == 9
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    RequestsInstrumentor().instrument(tracer_provider=provider)
    ThreadingInstrumentor().instrument(tracer_provider=provider)
    with provider.get_tracer("compatibility").start_as_current_span("test"):
        pass
    provider.force_flush()
    assert len(exporter.get_finished_spans()) == 1
    RequestsInstrumentor().uninstrument()
    ThreadingInstrumentor().uninstrument()
    provider.shutdown()
    options = {"verify_signature": False}
    token = jwt.encode({"exp": 1}, "synthetic-test-key-not-a-secret-32", algorithm="HS256")
    jwt.decode(token, options=options)
    assert options == {"verify_signature": False}
    options["verify_signature"] = True
    try:
        jwt.decode(token, "synthetic-test-key-not-a-secret-32", algorithms=["HS256"], options=options)
    except jwt.ExpiredSignatureError:
        pass
    else:
        raise AssertionError("expired claims accepted")
    print(json.dumps({"status":"PASS", "registered_mcp_tools": len(tools), "downstream_version":md.version("semgrep")}))


if __name__ == "__main__":
    main()
