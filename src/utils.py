#!/usr/bin/env python
# coding=utf-8

def remove_suffix(s, suffix):
    if s.endswith(suffix):
        return s[:-len(suffix)]
    return s
