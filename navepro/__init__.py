"""
NavePro - Sistema de Projeção para Igrejas.

Pacote da aplicação NavePro. Nesta etapa (Passo 1 da modularização)
contém a camada de infraestrutura pura (navepro.core) e as configurações
de topo (navepro.config), extraídas do monolito NavePro.py sem alteração
de comportamento.
"""

from navepro.config import APP_VERSION

__version__ = APP_VERSION