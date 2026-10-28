"""The "More from Season" carousel on an episode's page.

jellyfin-web's ``renderMoreFromSeason`` (itemDetails/index.js): an episode
that names its series and its season gets a row of that season's episodes,
hidden when the season has fewer than two, headed with the season's own name,
and scrolled so the episode you are on is near its start. The rules live in
``components/detail.py`` and the scroll seeding in ``pages/detail.py``; these
tests pin that the page actually calls them, and in the right place.
"""

# Run as a script, this is what puts the repo root on sys.path -- without
# it `jellyfin_mpv_shim` resolves to whatever is pip-installed. A no-op
# under `discover`; tests/test_module_paths.py is the guard.
if __name__ == "__main__":
    import os
    import sys

    sys.path.insert(0, os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))

import sys
import unittest

sys.argv = [sys.argv[0]]      # importing the shim reaches args.get_args()

from jellyfin_mpv_shim.mpvtk_browser.app import MpvtkBrowser  # noqa: E402
from jellyfin_mpv_shim.mpvtk_browser.components import (  # noqa: E402
    detail as detail_components)
from jellyfin_mpv_shim.mpvtk_browser.scroll_state import (  # noqa: E402
    ScrollState)

from tests._shell_harness import (  # noqa: E402
    FakeController, FakeSource, _SyncPool, build_scene, ids)

ROW = "detail-season"       # the prefix; a page's own row adds its episode id


def row_id(item_id):
    """One scroll container per episode page (``DetailPage._season_row_id``),
    so a page cannot collide with the one it was reached from."""
    return "%s-%s" % (ROW, item_id)
TALL = (1280, 3000)     # every row on one screen, so none is virtualized away
WIDE = (6000, 3000)     # wide enough that the row never draws page arrows


def season(n, still=True):
    """A season's episodes as ``get_episodes`` answers them."""
    return [{"Id": "e%d" % i, "Name": "Ep %d" % i, "Type": "Episode",
             "SeriesId": "sh1", "SeasonId": "se2", "SeasonName": "Season 2",
             "ParentIndexNumber": 2, "IndexNumber": i + 1,
             **({"ImageTags": {"Primary": "t%d" % i}} if still else {})}
            for i in range(n)]


def episode(iid="e0", **over):
    """An episode's own DTO, as ``get_item`` answers it. The server sets the
    series and season fields on every episode regardless of ``Fields``
    (DtoService.cs, ``if (item is Episode episode)``)."""
    dto = {"Id": iid, "Name": "Ep %s" % iid, "Type": "Episode",
           "SeriesId": "sh1", "SeriesName": "A Show", "SeasonId": "se2",
           "SeasonName": "Season 2", "ParentIndexNumber": 2,
           "IndexNumber": 1, "Overview": "An episode.", "ServerId": "SRVID",
           "People": [{"Id": "pp1", "Name": "Actor One", "Type": "Actor"}],
           "MediaSources": [{"Id": "src1", "Container": "mkv",
                             "MediaStreams": []}]}
    dto.update(over)
    return dto


def browser(item, episodes=None, app=None, **kw):
    """A browser on ``item``'s detail page, with the season it asks for.

    Every episode of the season is also an item the source can open, so a
    tile in the row leads somewhere real. ``app`` is the renderer stand-in,
    for tests that need the live scroll offsets a real one reports.
    """
    src = FakeSource()
    for e in (season(5) if episodes is None else episodes):
        src.items[e["Id"]] = episode(e["Id"])
    src.items[item["Id"]] = item
    src.season_calls = []
    eps = season(5) if episodes is None else episodes

    def get_episodes(server, series_id, season_id):
        src.season_calls.append((server, series_id, season_id))
        return list(eps)

    src.get_episodes = get_episodes
    b = MpvtkBrowser(app=app, source=src, controller=FakeController())
    b._pool = _SyncPool()
    b.server = "srv1"
    route = dict({"kind": "detail", "item_id": item["Id"], "server": "srv1"},
                 **kw)
    b.nav_stack = [route]
    b._load_route(b.route)
    return b


def row_tiles(b, size=WIDE):
    """The season row's tile ids on the page ``b`` is showing, without the
    scroll arrows that share their prefix when it overflows."""
    prefix = row_id(b.route["item_id"]) + "-"
    return [i for i in order(build_scene(b, size)[0])
            if i.startswith(prefix) and not i.endswith(("-pl", "-pr"))]


def has_row(nodes):
    """Whether a scene draws a season row at all."""
    return any((n.get("id") or "").startswith(ROW) for n in nodes)


def order(nodes):
    """Node ids in draw order. ``ids`` is a set and would lose it."""
    return [n.get("id") for n in nodes if n.get("id")]


class SceneRenderer:
    """``renderer.lua``'s scroll bookkeeping, and only that.

    Three rules of ``reconcile`` matter here and they are the whole bug
    between them: a container that is not in the scene it is handed LOSES its
    offset; one the renderer has no offset for opens at its ``off0`` (and is
    clamped, which a stand-in with no content cannot do); and
    ``scroll_offsets()`` answers from the scene most recently pushed, so on
    the first frame after a navigation it still describes the page being
    left. A container with neither an offset nor an ``off0`` has no entry.
    """

    def __init__(self):
        self.scroll = {}

    def invalidate(self):
        pass

    def scroll_offsets(self):
        return dict(self.scroll)

    def push(self, nodes):
        wanted = {n["id"]: n for n in nodes
                  if n.get("t") == "scroll" and n.get("id")}
        for gone in [k for k in self.scroll if k not in wanted]:
            del self.scroll[gone]
        for k, n in wanted.items():
            if k not in self.scroll and n.get("off0"):
                self.scroll[k] = float(n["off0"])


def show(b, renderer, size=WIDE):
    """Build a frame and hand it to the renderer, as the loop does."""
    nodes, handlers = build_scene(b, size)
    renderer.push(nodes)
    return nodes, handlers


def season_scroll(nodes):
    """The season row's scroll container in a scene."""
    found = [n for n in nodes if n.get("t") == "scroll"
             and (n.get("id") or "").startswith(ROW)
             and not (n["id"].endswith(("-pl", "-pr")))]
    assert len(found) == 1, "expected exactly one season row: %r" % (
        [n["id"] for n in found],)
    return found[0]


class ClickingThroughTest(unittest.TestCase):
    """Opening another episode from the row. The page being left has the
    same carousel, scrolled, still in the renderer when the new page's first
    frame is built -- and a restore is only ever applied to a container the
    renderer has not met."""

    def pitch(self, b):
        data = b.route["_data"]
        geom = b.tiles.caption_geom(data["season_episodes"],
                                    b.tiles.art.geom_wide)
        return geom.tile_w + geom.gap

    def click(self, b, r, nodes_handlers, target):
        nodes, handlers = nodes_handlers
        tile = "%s-%s" % (row_id(b.route["item_id"]), target)
        handlers[tile]["click"]()
        return show(b, r)

    def test_the_next_episode_opens_with_the_previous_one_first(self):
        r = SceneRenderer()
        b = browser(episode("e3"), app=r)
        first = show(b, r)
        pitch = self.pitch(b)
        self.assertEqual(season_scroll(first[0]).get("off0"), 2 * pitch,
                         "the page you arrive on")
        nodes, _ = self.click(b, r, first, "e4")
        self.assertEqual(b.route["item_id"], "e4")
        self.assertEqual(season_scroll(nodes).get("off0"), 3 * pitch)
        self.assertEqual(r.scroll_offsets()[season_scroll(nodes)["id"]],
                         3 * pitch, "and the renderer put it there")

    def test_an_earlier_episode_too(self):
        r = SceneRenderer()
        b = browser(episode("e4"), app=r)
        first = show(b, r)
        nodes, _ = self.click(b, r, first, "e2")
        self.assertEqual(season_scroll(nodes).get("off0"), 1 * self.pitch(b))

    def test_several_clicks_in_a_row_each_keep_the_rule(self):
        r = SceneRenderer()
        b = browser(episode("e1"), app=r)
        shown = show(b, r)
        for target, want in (("e3", 2), ("e4", 3), ("e2", 1), ("e4", 3)):
            shown = self.click(b, r, shown, target)
            self.assertEqual(b.route["item_id"], target)
            self.assertEqual(season_scroll(shown[0]).get("off0"),
                             want * self.pitch(b), target)

    def test_back_returns_to_the_page_where_it_was_left(self):
        r = SceneRenderer()
        b = browser(episode("e3"), app=r)
        first = show(b, r)
        self.click(b, r, first, "e4")
        b.go_back()
        nodes, _ = show(b, r)
        self.assertEqual(b.route["item_id"], "e3")
        row = season_scroll(nodes)
        self.assertEqual(r.scroll_offsets().get(row["id"]),
                         2 * self.pitch(b))


class TheRowTest(unittest.TestCase):
    def test_an_episode_lists_its_seasons_episodes_in_order(self):
        b = browser(episode("e2"))
        self.assertEqual(row_tiles(b), ["detail-season-e2-e%d" % i
                                        for i in range(5)])

    def test_it_asks_for_this_episodes_series_and_season(self):
        b = browser(episode("e2"))
        self.assertEqual(b.source.season_calls, [("srv1", "sh1", "se2")])

    def test_it_sits_after_scenes_and_before_cast_and_crew(self):
        chapters = [{"Name": "One", "StartPositionTicks": 0},
                    {"Name": "Two", "StartPositionTicks": 600000000}]
        b = browser(episode("e2", Chapters=chapters))
        seq = order(build_scene(b, TALL)[0])
        self.assertIn("detail-scenes", seq)
        mine = row_id("e2")
        self.assertLess(seq.index("detail-scenes"), seq.index(mine))
        self.assertLess(seq.index(mine), seq.index("detail-people"))

    def test_a_tile_click_opens_that_episodes_page(self):
        b = browser(episode("e2"))
        build_scene(b, WIDE)[1]["detail-season-e2-e4"]["click"]()
        self.assertEqual((b.route["kind"], b.route["item_id"]),
                         ("detail", "e4"))

    def test_every_tile_is_the_episodes_own_still(self):
        """A season's tiles must not borrow the series' artwork: the Thumb
        chain would draw one picture in every cell and the row would stop
        telling its episodes apart. Same pin as the season page's."""
        b = browser(episode("e2"))
        seen = {}
        real = b.tiles.image_map

        def spy(items, prefix, geom=None, image_type="Primary", **kw):
            if prefix == row_id("e2"):
                seen["inherit"] = kw.get("inherit", True)
            return real(items, prefix, geom, image_type, **kw)

        b.tiles.image_map = spy
        build_scene(b, WIDE)
        self.assertIn("inherit", seen, "the row was never built")
        self.assertFalse(seen["inherit"])


class TheGateTest(unittest.TestCase):
    """web: ``Type === 'Episode' && SeasonId && SeriesId``, then
    ``Items.length >= 2``. The first half is decided before any request."""

    def assert_no_row_and_no_request(self, item):
        b = browser(item)
        self.assertFalse(has_row(build_scene(b, TALL)[0]))
        self.assertEqual(b.source.season_calls, [])

    def test_a_movie_has_no_row_and_asks_nothing(self):
        self.assert_no_row_and_no_request(
            episode("m9", Type="Movie"))

    def test_an_episode_with_no_season_has_no_row_and_asks_nothing(self):
        item = episode("e2")
        del item["SeasonId"]
        self.assert_no_row_and_no_request(item)

    def test_an_episode_with_no_series_has_no_row_and_asks_nothing(self):
        item = episode("e2")
        del item["SeriesId"]
        self.assert_no_row_and_no_request(item)

    def test_a_season_of_one_has_no_row(self):
        """It would list only the episode already on screen."""
        b = browser(episode("e0"), episodes=season(1))
        self.assertEqual(b.source.season_calls, [("srv1", "sh1", "se2")])
        self.assertFalse(has_row(build_scene(b, TALL)[0]))

    def test_a_season_of_two_has_a_row(self):
        b = browser(episode("e0"), episodes=season(2))
        self.assertEqual(row_tiles(b), ["detail-season-e0-e0",
                                        "detail-season-e0-e1"])

    def test_an_empty_season_has_no_row(self):
        b = browser(episode("e0"), episodes=[])
        self.assertFalse(has_row(build_scene(b, TALL)[0]))

    def test_a_failed_fetch_costs_the_row_and_not_the_page(self):
        b = browser(episode("e2"))

        def boom(*_a):
            raise RuntimeError("500")

        b.source.get_episodes = boom
        b._load_route(b.route)
        nodes = build_scene(b, TALL)[0]
        self.assertIn("btn-play", ids(nodes))
        self.assertFalse(has_row(nodes))


class TheHeadingTest(unittest.TestCase):
    def test_the_servers_season_name_wins(self):
        """A renamed season keeps its name."""
        self.assertEqual(detail_components.season_name(
            {"SeasonName": "The Long Winter", "ParentIndexNumber": 2}),
            "The Long Winter")

    def test_the_number_stands_in_when_the_server_gave_no_name(self):
        self.assertEqual(detail_components.season_name(
            {"ParentIndexNumber": 3}), "Season 3")

    def test_season_zero_is_specials(self):
        self.assertEqual(detail_components.season_name(
            {"ParentIndexNumber": 0}), "Specials")

    def test_nothing_to_name_it_by_is_no_heading(self):
        self.assertIsNone(detail_components.season_name({}))
        self.assertIsNone(detail_components.season_name(None))

    def test_an_unnameable_season_draws_no_row(self):
        """The heading is "More from <name>"; without a name there is
        nothing honest to put after "from"."""
        item = episode("e2")
        del item["SeasonName"], item["ParentIndexNumber"]
        b = browser(item)
        self.assertFalse(has_row(build_scene(b, TALL)[0]))

    def test_the_heading_names_the_season(self):
        b = browser(episode("e2", SeasonName="The Long Winter"))
        heading = detail_components.season_row(
            b.tiles, b.route["_data"]["item"],
            b.route["_data"]["season_episodes"], row_id("e2"))
        self.assertIsNotNone(heading)
        texts = []

        def walk(el):
            texts.append(getattr(el, "text", None))
            for c in getattr(el, "children", None) or ():
                walk(c)

        walk(heading)
        self.assertIn("More from The Long Winter", texts)


class TheStartPositionTest(unittest.TestCase):
    """web scrolls the row so the previous episode leads, leaving the one
    you are on second. Seeded as a parked offset: the renderer applies it
    once, to a container it has not met."""

    def pitch(self, b):
        data = b.route["_data"]
        geom = b.tiles.caption_geom(data["season_episodes"],
                                    b.tiles.art.geom_wide)
        return geom.tile_w + geom.gap

    def parked(self, b):
        return ScrollState.parked(b.route, row_id(b.route["item_id"]))

    def test_a_late_episode_opens_the_row_one_tile_before_it(self):
        b = browser(episode("e3"))
        self.assertEqual(self.parked(b), 2 * self.pitch(b))

    def test_the_first_two_episodes_open_at_the_start(self):
        for iid in ("e0", "e1"):
            with self.subTest(iid):
                b = browser(episode(iid))
                self.assertIsNone(self.parked(b))

    def test_the_scene_carries_the_offset_to_the_row(self):
        b = browser(episode("e4"))
        row = season_scroll(build_scene(b, WIDE)[0])
        self.assertEqual(row["id"], row_id("e4"))
        self.assertEqual(row.get("off0"), 3 * self.pitch(b))

    def test_an_episode_the_season_does_not_list_opens_at_the_start(self):
        b = browser(episode("elsewhere"))
        self.assertIsNone(self.parked(b))

    def test_nothing_is_parked_when_there_is_no_row(self):
        b = browser(episode("e3"), episodes=season(1))
        self.assertIsNone(self.parked(b))

    def test_a_position_already_parked_is_left_alone(self):
        """A visit coming back, or the user's own scroll."""
        b = browser(episode("e3"),
                    **{ScrollState.PARK_KEY: {row_id("e3"): 123.0}})
        self.assertEqual(self.parked(b), 123.0)

    def test_other_parked_containers_survive_the_seed(self):
        b = browser(episode("e3"), **{ScrollState.PARK_KEY: {"detail": 40.0}})
        self.assertEqual(ScrollState.parked(b.route, "detail"), 40.0)
        self.assertEqual(self.parked(b), 2 * self.pitch(b))

    def test_a_refresh_does_not_walk_the_position(self):
        """Anything a poller or websocket can re-run is asserted over
        several runs: the seed is the same each time and the row is the same
        row."""
        b = browser(episode("e3"))
        first = self.parked(b)
        for _ in range(3):
            b._load_route(b.route)
            self.assertEqual(self.parked(b), first)
            self.assertEqual(len(row_tiles(b)), 5)

    def test_a_failing_seed_still_lands_the_page(self):
        """A start position is a nicety; losing it must not leave the page
        spinning with no data."""
        item = episode("e3")
        src_browser = browser(item)
        real = detail_components.season_start_offset

        def boom(*_a):
            raise RuntimeError("geometry")

        detail_components.season_start_offset = boom
        try:
            src_browser.route.pop("_data", None)
            src_browser.route.pop(ScrollState.PARK_KEY, None)
            src_browser._load_route(src_browser.route)
        finally:
            detail_components.season_start_offset = real
        self.assertIn("_data", src_browser.route)
        self.assertIn("btn-play", ids(build_scene(src_browser, TALL)[0]))


if __name__ == "__main__":
    unittest.main()


class ComingBackFromPlaybackTest(unittest.TestCase):
    """Play, stop, return: the row is where it was left.

    The loading screen is built after the park and before the window is given
    up, and the renderer still reports the old containers on that frame. That
    answer must not count as the restore having happened, or the returning
    row opens at its start.
    """

    def play_and_return(self, iid, scrolled=None, frames_between=1):
        r = SceneRenderer()
        b = browser(episode(iid), app=r)
        show(b, r)
        if scrolled is not None:
            r.scroll[row_id(iid)] = scrolled
        b.on_playstate({"stopped": False, "is_audio": False, "id": iid,
                        "title": "x", "position": 1, "duration": 100})
        for _ in range(frames_between):
            show(b, r)                  # the loading screen's frames
        r.push([])                      # the yield: an empty scene
        b.enter_browse()
        nodes, _ = show(b, r)
        return season_scroll(nodes).get("off0"), r

    def test_the_start_position_comes_back(self):
        for frames in (0, 1, 3):
            with self.subTest(frames=frames):
                off, r = self.play_and_return("e4", frames_between=frames)
                self.assertTrue(off, "the row came back at episode one")
                self.assertEqual(r.scroll[row_id("e4")], off)

    def test_the_users_own_scroll_comes_back(self):
        for frames in (0, 1, 3):
            with self.subTest(frames=frames):
                off, _ = self.play_and_return("e4", 77.0, frames)
                self.assertEqual(off, 77.0)

    def test_a_second_round_trip_holds_too(self):
        r = SceneRenderer()
        b = browser(episode("e4"), app=r)
        show(b, r)
        r.scroll[row_id("e4")] = 77.0
        for _ in range(3):
            b.on_playstate({"stopped": False, "is_audio": False,
                            "id": "e4", "title": "x", "position": 1,
                            "duration": 100})
            show(b, r)
            r.push([])
            b.enter_browse()
            nodes, _ = show(b, r)
            self.assertEqual(season_scroll(nodes).get("off0"), 77.0)
