"""A person's page: portrait, biography, details and two credit rows.

Laid out like the series screen (header, synopsis, provider links, rows) with
an episode-style header. The rules for the header's lines are in
``components/detail.py:person_lines`` and follow jellyfin-web's
``itemDetails``; the page is ``pages/person.py``.
"""

# Run as a script, this is what puts the repo root on sys.path -- without
# it `jellyfin_mpv_shim` resolves to whatever is pip-installed. A no-op
# under `discover`; tests/test_module_paths.py is the guard.
if __name__ == "__main__":
    import os
    import sys

    sys.path.insert(0, os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))

import datetime
import sys
import unittest
from types import SimpleNamespace as NS

sys.argv = [sys.argv[0]]      # importing the shim reaches args.get_args()

from jellyfin_mpv_shim.mpvtk.widgets import Text  # noqa: E402
from jellyfin_mpv_shim.mpvtk_browser.app import MpvtkBrowser  # noqa: E402
from jellyfin_mpv_shim.mpvtk_browser.components import (  # noqa: E402
    detail as detail_components)
from jellyfin_mpv_shim.mpvtk_browser.repository import (  # noqa: E402
    LibrarySource)

from tests._shell_harness import (  # noqa: E402
    FakeController, FakeSource, _SyncPool, build_scene, ids)

WIDE = (3000, 3000)     # every row on one screen, so none is virtualized away
TODAY = datetime.date(2026, 10, 29)

LUIS = {"Id": "p1", "Name": "Luis Guzmán", "Type": "Person",
        "PremiereDate": "1956-08-28T00:00:00.0000000Z",
        "ProductionLocations": ["Cayey, Puerto Rico"],
        "Overview": "An actor.\\nKnown for character work.".replace(
            "\\n", "\n"),
        "ExternalUrls": [{"Name": "IMDb", "Url": "https://imdb.example/1"}]}


def browser(person=None, **source):
    src = FakeSource()
    src.people = {"p1": person if person is not None else dict(LUIS)}
    for key, value in source.items():
        setattr(src, key, value)
    b = MpvtkBrowser(app=None, source=src, controller=FakeController())
    b._pool = _SyncPool()
    b.server = "srv1"
    route = {"kind": "person", "server": "srv1", "person_id": "p1",
             "title": "Luis Guzmán"}
    b.nav_stack = [route]
    b._load_route(b.route)
    return b


class _Thumbs:
    """A thumbnail store that has every image already: a 2:3 portrait."""

    def __init__(self):
        from PIL import Image

        self.image = Image.new("RGB", (512, 768), (180, 150, 130))
        self.store = {}

    def get_cached(self, key):
        return self.store.get(key)

    def request(self, key, url, box, callback, cover=False):
        im = self.image.copy()
        im.thumbnail(box)
        self.store[key] = im
        callback(im)

    def pump(self):
        return False

    def __getattr__(self, name):
        return lambda *a, **k: None


def with_portrait(b):
    b.tiles.art.server = "srv1"
    b.tiles.art.thumbs = b.thumbs = _Thumbs()
    return b


def texts(b, size=WIDE):
    """Every string the scene draws."""
    nodes, _h = build_scene(b, size)
    return [n.get("text") for n in nodes if n.get("text")]


class TheDetailsTest(unittest.TestCase):
    """The born / died / birth place lines."""

    def lines(self, **over):
        return detail_components.person_lines(dict(LUIS, **over), TODAY)

    def test_a_living_person_has_a_birth_date_and_an_age(self):
        self.assertEqual(self.lines()[:2], [
            "Born: 8/28/1956 (70 years old)", "Birth place: Cayey, Puerto Rico"
        ])

    def test_the_age_turns_over_on_the_birthday(self):
        for day, age in ((datetime.date(2026, 8, 27), 69),
                         (datetime.date(2026, 8, 28), 70)):
            with self.subTest(day=day):
                lines = detail_components.person_lines(dict(LUIS), day)
                self.assertIn("(%d years old)" % age, lines[0])

    def test_a_person_who_died_gets_the_age_they_died_at(self):
        """web moves the age to the death line, and only there."""
        lines = self.lines(EndDate="2020-01-02T00:00:00.0000000Z")
        self.assertEqual(lines[0], "Born: 8/28/1956")
        self.assertEqual(lines[1], "Died: 1/2/2020 (63 years old)")

    def test_the_date_is_the_servers_day_in_every_timezone(self):
        """Midnight UTC, read as a calendar date and not run through the
        local zone, which shows the day before west of Greenwich."""
        import os
        import time

        old = os.environ.get("TZ")
        os.environ["TZ"] = "America/Los_Angeles"
        time.tzset()
        try:
            self.assertEqual(self.lines()[0][:15], "Born: 8/28/1956")
        finally:
            if old is None:
                del os.environ["TZ"]
            else:
                os.environ["TZ"] = old
            time.tzset()

    def test_only_the_first_birth_place_is_shown(self):
        lines = self.lines(ProductionLocations=["A, B", "C, D"])
        self.assertEqual(lines[-1], "Birth place: A, B")

    def test_what_the_server_does_not_have_is_left_out(self):
        self.assertEqual(self.lines(PremiereDate=None,
                                    ProductionLocations=None), [])
        self.assertEqual(self.lines(ProductionLocations=[]),
                         ["Born: 8/28/1956 (70 years old)"])

    def test_a_date_it_cannot_read_is_no_date(self):
        for bad in ("", "not a date", "0000-00-00", "1956-13-40T00:00"):
            with self.subTest(bad=bad):
                self.assertEqual(
                    self.lines(PremiereDate=bad, ProductionLocations=None),
                    [])

    def test_a_death_date_without_a_birth_date_has_no_age(self):
        lines = self.lines(PremiereDate=None, ProductionLocations=None,
                           EndDate="2020-01-02T00:00:00Z")
        self.assertEqual(lines, ["Died: 1/2/2020"])


class _RecordingApi:
    def __init__(self):
        self.calls = []

    def get_item(self, item_id, fields=None):
        self.calls.append(("get_item", item_id, fields))
        return {"Id": item_id}

    def get_items_by_person(self, person_id, **kw):
        self.calls.append(("get_items_by_person", person_id, kw))
        return {"Items": [], "TotalRecordCount": 0}


class TheQueriesTest(unittest.TestCase):
    """What goes over the wire. The server drops a Field it is not asked
    for and an unknown one alike, so the names are the contract."""

    def repo(self):
        repo = LibrarySource.__new__(LibrarySource)
        api = _RecordingApi()
        repo._conns = {"s1": NS(api=api)}
        return repo, api

    def test_the_person_is_asked_for_the_fields_the_page_draws(self):
        repo, api = self.repo()
        repo.get_person("s1", "p1")
        _name, _id, fields = api.calls[-1]
        for want in ("Overview", "ProductionLocations", "ExternalUrls"):
            self.assertIn(want, fields.split(","))

    def test_each_row_is_its_own_query(self):
        repo, api = self.repo()
        repo.get_person_items("s1", "p1", include_item_types="Movie")
        repo.get_person_items("s1", "p1", include_item_types="Series")
        types = [c[2]["include_item_types"] for c in api.calls]
        self.assertEqual(types, ["Movie", "Series"])

    def test_the_default_is_still_both(self):
        repo, api = self.repo()
        repo.get_person_items("s1", "p1")
        self.assertEqual(api.calls[-1][2]["include_item_types"],
                         "Movie,Series")


class ThePageTest(unittest.TestCase):
    def test_it_asks_for_the_person_and_for_movies_and_shows_apart(self):
        b = browser()
        self.assertEqual(b.source.person_calls, ["p1"])
        kinds = sorted(q[0] for q in b.source.person_queries)
        self.assertEqual(kinds, ["Movie", "Series"])

    def test_movies_and_shows_are_rows_of_their_own(self):
        b = browser()
        nodes, _h = build_scene(b, WIDE)
        found = [i for i in ids(nodes) if isinstance(i, str)]
        movies = [i for i in found if i.startswith("person-movies-")
                  and not i.endswith(("-pl", "-pr"))]
        shows = [i for i in found if i.startswith("person-shows-")
                 and not i.endswith(("-pl", "-pr"))]
        self.assertEqual(len(movies), 4)
        self.assertEqual(len(shows), 2)
        self.assertTrue(all(i.startswith("person-movies-pf") for i in movies),
                        "a show landed in the movies row: %r" % movies)
        self.assertTrue(all(i.startswith("person-shows-ps") for i in shows),
                        "a film landed in the shows row: %r" % shows)

    def test_the_rows_are_headed(self):
        out = texts(browser())
        self.assertIn("Movies", out)
        self.assertIn("Shows", out)

    def test_a_row_with_nothing_in_it_is_not_drawn(self):
        b = browser()
        b.route["_data"]["shows"] = []
        out = texts(b)
        self.assertIn("Movies", out)
        self.assertNotIn("Shows", out)

    def test_no_credits_says_so(self):
        b = browser()
        b.route["_data"]["movies"] = []
        b.route["_data"]["shows"] = []
        self.assertIn("No movies or shows found.", texts(b))

    def test_the_biography_is_drawn(self):
        out = texts(browser())
        self.assertIn("An actor.", out)
        self.assertIn("Known for character work.", out)

    def test_the_provider_links_are_drawn(self):
        nodes, _h = build_scene(browser(), WIDE)
        self.assertIn("detail-link-0", ids(nodes))
        self.assertIn("detail-web-link", ids(nodes))

    def test_order_is_header_biography_links_movies_shows(self):
        nodes, _h = build_scene(browser(), WIDE)
        order = [n.get("id") for n in nodes if n.get("id")]

        def at(prefix):
            return next(i for i, n in enumerate(order)
                        if str(n).startswith(prefix))

        self.assertLess(at("detail-link-0"), at("person-movies-"))
        self.assertLess(at("person-movies-"), at("person-shows-"))

    def test_a_person_the_server_cannot_describe_still_gets_credits(self):
        """The person is decoration around the credits."""
        b = browser()
        b.source.get_person = lambda *a: (_ for _ in ()).throw(OSError("x"))
        b._load_route(b.route)
        out = texts(b)
        self.assertIn("Luis Guzmán", out, "the name the click carried")
        self.assertIn("Movies", out)

    def test_an_offline_person_comes_up_with_just_the_name(self):
        b = browser()
        b.source.get_person = lambda *a: None
        b.source.get_person_items = lambda *a, **k: ([], 0)
        b._load_route(b.route)
        out = texts(b)
        self.assertIn("Luis Guzmán", out)
        self.assertIn("No movies or shows found.", out)

    def test_the_name_and_details_are_drawn(self):
        out = texts(browser())
        self.assertIn("Luis Guzmán", out)
        self.assertIn("Born: 8/28/1956 (70 years old)", out)
        self.assertIn("Birth place: Cayey, Puerto Rico", out)

    def test_no_banner_is_drawn(self):
        """A person has no backdrop, and the inset-poster header hides behind
        a setting about film art. The portrait is part of the page itself."""
        nodes, _h = build_scene(browser(has_poster=True), WIDE)
        self.assertNotIn("person-bd", ids(nodes))

    def test_the_portrait_is_asked_for_whatever_the_poster_setting_says(self):
        from jellyfin_mpv_shim.conf import settings

        old = settings.detail_poster
        settings.detail_poster = False
        try:
            b = browser(has_poster=True)
            b.tiles.art.server = "srv1"
            asked = []
            real = b.tiles.art_cell
            b.tiles.art_cell = lambda item, size=28: (
                asked.append((item.get("Id"), size)), real(item, size))[1]
            build_scene(b, WIDE)
        finally:
            settings.detail_poster = old
        self.assertEqual([a[0] for a in asked], ["p1"])

    def test_the_portrait_sits_left_of_the_text_on_its_baseline(self):
        """Left of the name and the lines, and the block bottom-aligned with
        it, as in the mockup."""
        b = with_portrait(browser(has_poster=True))
        build_scene(b, WIDE)
        nodes, _h = build_scene(b, WIDE)
        by_text = {n["text"]: n for n in nodes if n.get("text")}
        name = by_text["Luis Guzmán"]
        place = by_text["Birth place: Cayey, Puerto Rico"]
        images = [n for n in nodes if n.get("t") == "img"
                  and n["y"] < name["y"] + name["h"]
                  and n["x"] < name["x"]]
        self.assertTrue(images, "no portrait left of the name")
        portrait = max(images, key=lambda n: n["h"])
        self.assertLess(portrait["x"] + portrait["w"], name["x"])
        self.assertAlmostEqual(portrait["y"] + portrait["h"],
                               place["y"] + place["h"], delta=2,
                               msg="the text does not rest on the portrait")

    def test_a_person_with_no_image_tag_is_still_asked_for_one(self):
        """The DTO is the server's word that there is a portrait, but a
        person that came back without ImageTags is not proof there is none."""
        person = dict(LUIS)
        person.pop("ImageTags", None)
        b = browser(person, has_poster=True)
        b.tiles.art.server = "srv1"
        seen = []
        real = b.source.image_spec
        b.source.image_spec = lambda item, *a, **k: (
            seen.append(item.get("ImageTags")), real(item, *a, **k))[1]
        build_scene(b, WIDE)
        self.assertIn({"Primary": "person"}, seen)

    def test_the_portrait_height_moves_in_steps(self):
        """It is part of the artwork request, so a window drag must not mint
        a new request per pixel."""
        b = browser(has_poster=True)
        b.tiles.art.server = "srv1"
        heights = set()
        real = b.tiles.art_cell
        b.tiles.art_cell = lambda item, size=28: (
            heights.add(size), real(item, size))[1]
        for h in range(600, 1200, 7):
            build_scene(b, (1280, h))
        self.assertLessEqual(len(heights), 5)
        self.assertTrue(all(240 <= v <= 432 for v in heights), heights)

    def test_a_refresh_does_not_change_what_is_drawn(self):
        """Anything a poller or websocket can re-run is asserted over
        several runs."""
        b = browser()
        first = texts(b)
        for _ in range(3):
            b._load_route(b.route)
            self.assertEqual(texts(b), first)

    def test_clicking_a_credit_opens_it(self):
        b = browser()
        _nodes, handlers = build_scene(b, WIDE)
        tile = next(i for i in handlers if str(i).startswith("person-movies-")
                    and not str(i).endswith(("-pl", "-pr"))
                    and handlers[i].get("click"))
        handlers[tile]["click"]()
        self.assertEqual(b.route["kind"], "detail")


if __name__ == "__main__":
    unittest.main()
