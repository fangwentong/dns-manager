#!/usr/bin/env python
# coding=utf-8

import logging
import functools


logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')


def log_api_call(func):
    """
    A decorator that wraps a function in a try-except block and logs exceptions.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        class_name = args[0].__class__.__name__ if args else ''
        func_name = func.__name__ 
        try:
            return func(*args, **kwargs)
        except Exception as e:
            # repr(arg) is used to get a developer-friendly representation of the object
            arg_details = [repr(arg) for arg in args[1:]]  # Skip self
            kwarg_details = [f"{k}={repr(v)}" for k, v in kwargs.items()]
            all_args = ", ".join(arg_details + kwarg_details)

            logging.error(
                f"[{class_name}.{func_name}] API call failed.\n"
                f">> INPUT: ({all_args})\n"
                f">> EXCEPTION: {e}"
            )
            raise
    return wrapper


def remove_suffix(s, suffix):
    if s.endswith(suffix):
        return s[:-len(suffix)]
    return s