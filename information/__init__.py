"""
information — 건물정보 분석 (풍하중 · 지진하중 · 설하중)
launcher.py 의 'Information' 카드에서 open_information() 으로 연다.
"""


def open_information(parent, username=""):
    from .app import InformationApp
    return InformationApp(parent, username=username)
