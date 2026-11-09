"""x402 가격 단위와 Solana USDC 인식(2026-11-10, 운영·SRE).

resources.price_usdc는 USDC 원자 단위 정수(소수 6자리, 10000 = $0.01)다. x402의 amount도 원자 단위
정수 문자열이라 BIGINT가 맞다. Solana USDC 발행 주소 상수에 'g'가 하나 더 있어 Solana USDC 조건이
가격 계산에서 빠졌다(운영: 가격 없음 26개, 더 비싸게 저장 99개)."""
from agent_market.gateway.crawler import USDC_ASSETS, usdc_price

SOLANA = 'solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp'
SOLANA_USDC = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'  # Circle's USDC mint on Solana mainnet
BASE_USDC = '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913'


def test_solana_usdc_mint_matches_the_real_address():
    assert USDC_ASSETS[SOLANA] == SOLANA_USDC.lower()


def test_solana_only_listing_gets_a_price():
    accepts = [{'network': SOLANA, 'asset': SOLANA_USDC, 'amount': '10000', 'payTo': 'Bn7s'}]
    assert usdc_price(accepts) == (10000, 'Bn7s', SOLANA)


def test_cheapest_usdc_option_wins_across_networks():
    accepts = [{'network': 'eip155:8453', 'asset': BASE_USDC, 'amount': '20000', 'payTo': '0xab'},
               {'network': SOLANA, 'asset': SOLANA_USDC, 'amount': '5000', 'payTo': 'sol'}]
    assert usdc_price(accepts)[0] == 5000


def test_decimal_amounts_of_other_assets_never_become_zero():
    # XRPL RLUSD quotes decimals ("0.01"); they are not USDC atomic units and are skipped, not truncated.
    accepts = [{'network': 'xrpl:0', 'asset': '524C555344000000000000000000000000000000', 'amount': '0.01'},
               {'network': 'eip155:8453', 'asset': BASE_USDC, 'amount': '10000', 'payTo': '0xab'}]
    assert usdc_price(accepts)[0] == 10000
    assert usdc_price(accepts[:1]) is None
