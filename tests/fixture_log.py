"""Stub silencioso de logging para as suítes que executam trechos do NavePro.py.

Os trechos extraídos via AST referenciam o logger global `log` (navepro.core.log);
aqui ele é um logger de verdade, mas sem handlers e sem propagação — assim os
testes não emitem nada mesmo em WARNING/ERROR.
"""

import logging

log = logging.getLogger("navepro.teste")
log.addHandler(logging.NullHandler())
log.propagate = False
