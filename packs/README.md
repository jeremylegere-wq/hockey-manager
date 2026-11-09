# packs/

A data pack is a folder of CSV files that describes a league: clubs, players, ratings, contracts, rules. The game turns a
pack into a world you can start a career in. Start from `example_fictional/` (8 invented clubs) or generate the
32-club one:

    python -m hs.tools.make_mock_league packs/my_league        # 32 invented clubs, 892 players, a salary cap, 84 games
    python -m hs.datapack packs/my_league                      # check it
    python -m hs.tools.build_world packs/my_league packs/my_world --fictional    # add the farm, junior, college, Europe
    python -m hs.ingest packs/my_world worlds/My_League.db     # build the world; it appears on New Game's World step

Everything in this folder except this file and `example_fictional/` is git-ignored: do not commit packs that contain other
people's data. The full guide is `docs/BUILD_YOUR_OWN.md`; the file format is `docs/DATAPACK_SPEC.md`.
