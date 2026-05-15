from champions_ai.engine import ChampionsAI, BattleState, PokemonState


def test_suggest_basic():
    ai = ChampionsAI('/workspace/Pokemon-Simulation')
    my = [
        PokemonState(name='ピカチュウ', hp=80, item='ピカチュウナイトメガストーン', moves=['ボルテッカー','ねこだまし','アンコール','まもる']),
        PokemonState(name='フシギダネ', hp=100, moves=['やどりぎのタネ']),
        PokemonState(name='ヒトカゲ', hp=100, moves=['かえんほうしゃ']),
    ]
    opp = [PokemonState(name='フシギダネ')]
    st = BattleState(my_active='ピカチュウ', opp_active='フシギダネ', my_party=my, opp_party=opp, selected3=['ピカチュウ','フシギダネ','ヒトカゲ'])
    out = ai.suggest(st)
    assert out
    assert any(a.kind=='move' for a,_,_ in out)
