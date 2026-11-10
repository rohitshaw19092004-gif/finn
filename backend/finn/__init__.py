"""FINN — Financial Investment agent.

Server side handles *public* market intelligence only (prices, exchange filings,
fundamentals, people named in filings). The investor's private network never
reaches this package: matching happens on the investor's device (see web/src/network).
"""

__version__ = "0.1.0"
