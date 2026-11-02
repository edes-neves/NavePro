"""
NavePro - Sistema de Projeção Profissional.

Pacote da aplicação NavePro: infraestrutura sem Tk (navepro.core), as
janelas do painel como mixins (navepro.ui), as configurações de topo
(navepro.config), a página do controle remoto (navepro.remoto_web) e o
sorteio embutido (navepro.sorteio). O shell da interface fica em
NavePro.py (AppInterface herda os mixins).
"""

from navepro.config import APP_VERSION

__version__ = APP_VERSION