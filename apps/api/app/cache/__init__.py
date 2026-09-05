"""Redis access layer.

Redis is the locked cache/queue technology (SRS TS-05). There is deliberately
no in-memory replacement here: when Redis is disabled the provider reports it
instead of silently emulating it - see docs/adr/ADR-0003.
"""
