"""Shared domain types: contract parsing, predicates and (later) the safety-rule library.

Backend, Controller and Decision all import this package, so it must stay free of heavy
dependencies. In particular it must not import optuna: the bench process loads it too.
"""
