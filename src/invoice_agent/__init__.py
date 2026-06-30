"""Invoice-intake agent package.

An OpenAI Agents SDK agent that ingests an inbound email and its PDF invoice
attachment, extracts structured invoice data (including fields embedded in a PDF
image), and produces a notification for Customer Service.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
