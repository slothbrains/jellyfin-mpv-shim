"""A person's screen: portrait, details, biography, and what they were in.

Laid out like the series screen -- header, synopsis (here a biography),
provider links, then carousels -- but with a header of its own instead of
a banner: the portrait on the left, and the name, born / died and birth
place beside it, bottom-aligned with it.

No banner because a person has nothing to put behind one (no backdrop, and a
2:3 portrait cropped into a wide strip looks like a fault), and because the
inset-poster header is switched off by the "Show Posters on Detail Pages"
setting, which is about film art and not about whose face this is.

Replaces the grid this route used to be. The grid was one flat, sortable
list of everything a person was credited on, which is what a person
appears in but not what anyone opening the page wants first; the portrait
and the biography had nowhere to go in it, and movies and shows were
interleaved by name.
"""

from ...i18n import _
from ...mpvtk.widgets import Column, Row, Text, VScroll
from .. import theme
from ..components import chrome, detail as detail_components
from .base import Page


class PersonPage(Page):
    kind = "person"

    #: The portrait's height range, in logical px. The top is about what a
    #: 1080p window gives it; the bottom keeps a face recognisable in a short
    #: one. Chosen in STEP-sized tiers rather than continuously, because the
    #: height is part of the artwork request and a window drag would
    #: otherwise ask the server for a new picture on every pixel (#592).
    PORTRAIT_MIN, PORTRAIT_MAX, PORTRAIT_STEP = 240, 432, 48

    #: Of the window's height.
    PORTRAIT_FRAC = 0.4

    #: Stands in for the Primary tag when the DTO names none. The server
    #: answers an image request whatever the tag is (it only keys caching),
    #: and a person with no portrait answers 404, which the thumbnail store
    #: records and stops asking about -- the same arrangement a playlist's
    #: generated art uses (``LibrarySource.image_spec``).
    UNTAGGED = "person"

    # -- load --------------------------------------------------------------

    def load(self, epoch):
        route = self.route
        source = self.ctx.source
        srv = route.get("server") or self.ctx.server
        pid = route["person_id"]

        def work():
            # The person is decoration around the credits, so failing to
            # read them is not a failed page: the rows still draw, under
            # the name the click carried. The credits failing IS one, and
            # raises into `route_async` for the retry it offers.
            person = None
            try:
                person = source.get_person(srv, pid)
            except Exception:
                pass
            movies, _total = source.get_person_items(
                srv, pid, include_item_types="Movie")
            shows, _total = source.get_person_items(
                srv, pid, include_item_types="Series")
            return {"person": person, "movies": movies, "shows": shows}

        self.route_async(work, lambda d: route.__setitem__("_data", d), epoch)

    # -- render ------------------------------------------------------------

    def render(self, size):
        tiles = self.ctx.art.tiles
        route = self.route
        data = route.get("_data")
        if data is None:
            return chrome.busy()
        item = dict(data.get("person") or {})
        item.setdefault("Id", route.get("person_id"))
        item.setdefault("Type", "Person")
        name = item.get("Name") or route.get("title") or ""
        item["Name"] = name
        w = size[0]
        lines = detail_components.person_lines(item)
        details = [Text(name, size="hero", bold=True, wrap=True,
                        w=tiles.body_w(w) // 2)]
        details += [Text(line, size="large", color=theme.SUBTLE_FG)
                    for line in lines]
        portrait = self._portrait(item, size[1])
        # Bottom-aligned, like the heading in a detail banner: the name and
        # the lines read as one block resting on the portrait's baseline.
        header = (Row([portrait, Column(details, gap=8)], gap=28,
                      align="end") if portrait is not None
                  else Column(details, gap=8))
        blocks = []
        text = chrome.overview(item)
        if text:
            blocks.append(chrome.paragraph(text, 18, tiles.body_w(w)))
        links = detail_components.provider_links(item, tiles.body_w(w),
                                                 self.open_link,
                                                 web_url=self.web_url(item))
        if links is not None:
            blocks.append(links)
        movies, shows = data.get("movies") or [], data.get("shows") or []
        if movies:
            blocks.append(tiles.tile_row(_("Movies"), movies,
                                         "person-movies"))
        if shows:
            blocks.append(tiles.tile_row(_("Shows"), shows, "person-shows"))
        if not movies and not shows:
            blocks.append(Text(_("No movies or shows found."), size="large",
                               color=theme.SUBTLE_FG))
        return Column([VScroll(
            chrome.header_body(header, blocks, gap=16),
            id="person", flex=1, offset=self.parked_scroll("person"))],
            flex=1, align="stretch")

    def _portrait(self, item, window_h):
        """The person's Primary image as a node, or None while there is no
        way to draw one (no server, offline)."""
        tiles = self.ctx.art.tiles
        if tiles.art.server is None:
            return None
        steps = int(window_h * self.PORTRAIT_FRAC) // self.PORTRAIT_STEP
        height = max(self.PORTRAIT_MIN,
                     min(self.PORTRAIT_MAX, steps * self.PORTRAIT_STEP))
        if not (item.get("ImageTags") or {}).get("Primary"):
            item = dict(item, ImageTags=dict(item.get("ImageTags") or {},
                                             Primary=self.UNTAGGED))
        node = tiles.art_cell(item, height)
        return node
