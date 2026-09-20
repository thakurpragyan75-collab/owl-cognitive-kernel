"""OWL Cognitive Kernel — compile intent, execute a DAG, verify, replay."""

from .ir.schema import Intent, Action
from .ir.compiler import compile_intent
from .kernel.engine import Kernel
from .protocol.v1 import PROTOCOL_VERSION

__version__ = "0.1.0"
__all__ = ["Intent", "Action", "compile_intent", "Kernel", "PROTOCOL_VERSION"]
