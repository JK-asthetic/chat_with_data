"""Product-hierarchy rows shaped like SELECT DISTINCT product_l1..l5 FROM data_arr (a leaf repeats its own name)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import companies, hierarchy  # noqa: E402

ROWS = [dict(zip(("product_l1", "product_l2", "product_l3", "product_l4", "product_l5"), r)) for r in [
    ("ZIA", "SWG", "Core SWG", "SWG - Add-on", "Proxy Port"),
    ("ZIA", "SWG", "Core SWG", "Core SWG", "Core SWG"),
    ("ZIA", "SWG", "China Premium", "China Premium Add-On", "China Premium Infra"),
    ("ZIA", "SWG", "Private Infra - ZIA", "Private Infra - ZIA", "Private Infra - ZIA"),
    ("ZIA", "Firewall", "Firewall", "Firewall", "Firewall"),
    ("ZIA", "Sandbox", "Sandbox", "Sandbox", "Sandbox"),
    ("ZIA", "ZIA Standard", "Firewall Standard", "Firewall Standard", "Firewall"),
    ("ZPA", "Private Access", "Core ZPA", "Private Access", "User Portal"),
    ("ZPA", "Private Access", "China Premium", "China Premium Access", "China Premium Access"),
    ("Digital Experience", "ZDX", "ZDX", "ZDX", "ZDX"),
]]


def install_hierarchy() -> None:
    """Use the fixtures instead of querying the database."""
    hierarchy._INDEX = hierarchy.build_index(ROWS)
    companies.existing = lambda candidates, exact=False: set()
