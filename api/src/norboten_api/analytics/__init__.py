"""The Analytics page: what the attempts say about the labs, the questions and the learners.

Everything is computed from two tables — users and attempts — with pandas, scikit-learn and
networkx, and drawn with matplotlib into SVG in the site's own colours. There is no model and no
sampling: every number on the page can be recomputed from the database with the SQL it implies.

Where the data comes from:

* on the server, PostgreSQL (`--database-url`), by a nightly job that writes into the site;
* at site build and on a laptop, the generated sample population (`seed/accounts.json`) — and the
  page says so in its first line.

    python -m norboten_api.analytics --seed seed/accounts.json --out site/dist/analytics
    python -m norboten_api.analytics --database-url postgresql://… --out /srv/site/analytics
"""

from norboten_api.analytics.data import Frames, from_postgres, from_seed
from norboten_api.analytics.figures import render_all

__all__ = ["Frames", "from_postgres", "from_seed", "render_all"]
