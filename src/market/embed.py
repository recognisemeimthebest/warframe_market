"""시세 조회 결과를 Discord embed로 포맷팅."""

import discord

from src.market.api import ItemPrice


def price_embed(price: ItemPrice) -> discord.Embed:
    """ItemPrice를 Discord Embed로 변환한다."""
    embed = discord.Embed(
        title=f"{price.item_name} 시세",
        url=f"https://warframe.market/items/{price.slug}",
        color=0x4DB8FF,
    )

    # 판매 최저가
    if price.sell_min is not None:
        embed.add_field(
            name="판매 최저가",
            value=f"**{price.sell_min}p** ({price.sell_count}건)",
            inline=True,
        )
    else:
        embed.add_field(name="판매 최저가", value="등록 없음", inline=True)

    # 구매 최고가
    if price.buy_max is not None:
        embed.add_field(
            name="구매 최고가",
            value=f"**{price.buy_max}p** ({price.buy_count}건)",
            inline=True,
        )
    else:
        embed.add_field(name="구매 최고가", value="등록 없음", inline=True)

    # 48시간 평균
    if price.avg_48h is not None:
        embed.add_field(
            name="48시간 평균",
            value=f"**{price.avg_48h:.1f}p** (거래 {price.volume_48h}건)",
            inline=True,
        )

    embed.set_footer(text="warframe.market 기준 · 온라인/인게임 유저만 표시")
    return embed


def not_found_embed(query: str) -> discord.Embed:
    """아이템을 찾지 못했을 때의 embed."""
    return discord.Embed(
        title="아이템을 찾지 못했어요",
        description=f'"{query}"에 해당하는 아이템이 없어요.\n영문 이름이나 다른 표현으로 다시 시도해보세요!',
        color=0xFF6B6B,
    )
