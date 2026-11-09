"""The Manager Profile screen's data (phase A2): ratings and what they do, reputation and its history, role, options."""
from __future__ import annotations

from ..game import gm as GMx


def manager_view(conn):
    s = GMx.settings(conn)
    return dict(settings=s, ratings=[dict(key=k, label=l, what=w, value=s["ratings"].get(k, 10)) for k, (l, w) in GMx.RATINGS.items()],
                reputation_label=GMx.reputation_label(s["reputation"]), role_label=GMx.ROLES_GM.get(s["role"], s["role"]),
                is_coach=GMx.is_coach(conn), unemployed=GMx.unemployed(conn), pool=GMx.POOL, r_min=GMx.R_MIN, r_max=GMx.R_MAX,
                templates={k: dict(label=l, ratings=r) for k, (l, r) in GMx.TEMPLATES.items()},
                reputations={k: dict(label=l, value=v) for k, (l, v) in GMx.REPUTATIONS.items()}, roles=GMx.ROLES_GM)


def setup_options():
    """For the new-game wizard (no save open)."""
    return dict(ratings=[dict(key=k, label=l, what=w) for k, (l, w) in GMx.RATINGS.items()], pool=GMx.POOL, r_min=GMx.R_MIN, r_max=GMx.R_MAX,
                templates={k: dict(label=l, ratings=r) for k, (l, r) in GMx.TEMPLATES.items()},
                reputations={k: dict(label=l, value=v) for k, (l, v) in GMx.REPUTATIONS.items()}, roles=GMx.ROLES_GM)
