import os
import re
import asyncio
import json
import ast
from functools import partial
from typing import Any, Iterable, Optional

import discord
from discord import app_commands
from dotenv import load_dotenv

from src.pipeline import answer, ingest_url, ingest_file_bytes
from src import memory

load_dotenv()

from pathlib import Path
import time as _t

try:
    p = Path(".cache") / "functions.json"
    for _ in range(3):
        if p.exists():
            try:
                p.unlink()
                break
            except PermissionError:
                _t.sleep(0.2)
except Exception:
    pass

TOKEN = os.getenv("DISCORD_TOKEN")
PREFIX = "!ask"
GUILD_ID = os.getenv("GUILD_ID")
GUILD = discord.Object(id=int(GUILD_ID)) if GUILD_ID else None


def _human(s: str) -> str:
    return s.replace("_", " ").strip().capitalize()


def _join(parts: Iterable[str]) -> str:
    return " ".join(p.strip() for p in parts if p and str(p).strip())


def _natural_list(items: Iterable[str]) -> str:
    items = [i for i in (x.strip() for x in items) if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def _cases_to_text(value: Any) -> str | None:
    cases = []
    if isinstance(value, list):
        for it in value:
            if isinstance(it, dict):
                name = it.get("case_name") or it.get("name") or it.get("title")
                year = it.get("year")
                outcome = it.get("outcome") or it.get("holding") or it.get("summary")
                if name and outcome:
                    if year:
                        cases.append(f"• {name} ({year}) — {outcome}")
                    else:
                        cases.append(f"• {name} — {outcome}")
    if cases:
        return "Key cases and outcomes:\n" + "\n".join(cases)
    return None


def _executive_order_to_text(key: str, payload: dict) -> str:
    status = payload.get("status") or payload.get("state")
    signed = payload.get("date_signed") or payload.get("signed")
    desc = payload.get("description")
    last = payload.get("last_confirmed") or payload.get("last_checked")
    amend = (
        payload.get("amendments_or_repeals")
        or payload.get("amendments")
        or payload.get("repeals")
    )
    lead = _human(key)
    bits = []
    if status:
        bits.append(f"It is **{status}**")
    if signed:
        bits.append(f"since {signed}")
    if last:
        bits.append(f"(last confirmed {last})")
    header = f"{lead}: " + _join(bits) + "."
    tail = (
        (" " + (desc or "").strip())
        if isinstance(desc, str) and desc and desc.strip()
        else ""
    )
    if isinstance(amend, str) and amend.strip() and amend.lower() not in ("none", "no"):
        tail += f" Amendments or repeals noted: {amend}."
    return (header + tail).strip()


def _dict_to_natural(d: dict) -> str:
    if len(d) == 1:
        k, v = next(iter(d.items()))
        if isinstance(v, dict):
            key_low = str(k).lower()
            if (
                "executive" in key_low
                or "order" in key_low
                or key_low.startswith("eo_")
            ):
                return _executive_order_to_text(k, v)
            parts = []
            for kk, vv in v.items():
                kk_h = _human(kk)
                if isinstance(vv, (str, int, float)):
                    parts.append(f"{kk_h}: {vv}.")
                elif isinstance(vv, list) and all(
                    isinstance(x, (str, int, float, str)) for x in vv
                ):
                    parts.append(f"{kk_h}: {_natural_list([str(x) for x in vv])}.")
            if parts:
                return f"{_human(k)} — " + " ".join(parts)
        if isinstance(v, list) and "case" in str(k).lower():
            txt = _cases_to_text(v)
            if txt:
                return txt

    for kk, vv in d.items():
        if "case" in str(kk).lower():
            text = _cases_to_text(vv)
            if text:
                return text

    flat_bits = []
    for k, v in d.items():
        kh = _human(k)
        if isinstance(v, (str, int, float)):
            flat_bits.append(f"{kh}: {v}.")
        elif isinstance(v, list) and all(
            isinstance(x, (str, int, float, str)) for x in v
        ):
            flat_bits.append(f"{kh}: {_natural_list([str(x) for x in v])}.")
    if flat_bits:
        return " ".join(flat_bits)
    return str(d)


def _themes_to_text(themes: list[dict]) -> str:
    lines = []
    for t in themes:
        theme = t.get("theme") or "Theme"
        desc = t.get("description") or ""
        cite = t.get("citation")
        line = f"• {theme} — {desc}".strip()
        if cite:
            line += f" (cite: {cite})"
        lines.append(line)
    return "Key enforcement themes:\n" + "\n".join(lines)


def _strip_code_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```") and s.endswith("```"):
        s = s[3:-3].strip()
        first_newline = s.find("\n")
        if first_newline != -1 and s[:first_newline].lower() in {"json", "python"}:
            s = s[first_newline + 1 :].strip()
    return s


def _maybe_parse_structured_string(s: str) -> Any | None:
    if not isinstance(s, str):
        return None
    txt = _strip_code_fences(s).strip()
    if not (txt.startswith("{") or txt.startswith("[")):
        return None
    try:
        return json.loads(txt)
    except Exception:
        pass
    try:
        return ast.literal_eval(txt)
    except Exception:
        return None


def _extract_raw_output(result: Any) -> str | None:
    if isinstance(result, str):
        return _strip_code_fences(result).strip()

    for attr in ("output", "text", "message", "content"):
        if hasattr(result, attr) and getattr(result, attr):
            return _strip_code_fences(str(getattr(result, attr))).strip()

    data = getattr(result, "data", None)
    if data is None:
        return None

    try:
        if hasattr(data, "to_dict"):
            data = data.to_dict()
    except Exception:
        pass

    if isinstance(data, (str, int, float)):
        return _strip_code_fences(str(data)).strip()

    if isinstance(data, dict):
        for k in ("output", "text", "message", "content"):
            v = data.get(k)
            if isinstance(v, (str, int, float)):
                return _strip_code_fences(str(v)).strip()
        try:
            return json.dumps(data, indent=2)
        except Exception:
            return str(data)

    for attr in ("output", "text", "message", "content"):
        v = getattr(data, attr, None)
        if v:
            return _strip_code_fences(str(v)).strip()

    return None


def _to_text(result: Any) -> str:
    if isinstance(result, str):
        parsed = _maybe_parse_structured_string(result)
        if parsed is not None:
            return _to_text(parsed)
        return result.strip()

    for attr in ("text", "output", "message", "content"):
        if hasattr(result, attr) and getattr(result, attr):
            val = getattr(result, attr)
            if isinstance(val, str):
                parsed = _maybe_parse_structured_string(val)
                return _to_text(parsed) if parsed is not None else val.strip()

    data = getattr(result, "data", None)
    if data is not None:
        try:
            if hasattr(data, "to_dict"):
                data = data.to_dict()
        except Exception:
            pass

        if isinstance(data, str):
            parsed = _maybe_parse_structured_string(data)
            return _to_text(parsed) if parsed is not None else data.strip()

        if isinstance(data, dict):
            out = (
                data.get("output")
                or data.get("text")
                or data.get("message")
                or data.get("content")
            )
            if isinstance(out, str):
                parsed = _maybe_parse_structured_string(out)
                return _to_text(parsed) if parsed is not None else out.strip()
            if isinstance(out, dict):
                themes = out.get("summary", {}).get("themes")
                if isinstance(themes, list) and themes:
                    return _themes_to_text(themes)
                return _dict_to_natural(out)
            return _dict_to_natural(data)

        for attr in ("output", "text", "message", "content"):
            v = getattr(data, attr, None)
            if isinstance(v, str):
                parsed = _maybe_parse_structured_string(v)
                return _to_text(parsed) if parsed is not None else v.strip()

    try:
        return _dict_to_natural(dict(result))
    except Exception:
        return str(result)


def _clean_sources(text: str) -> str:
    lines = text.strip().split("\n")
    cleaned_lines = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        line = re.sub(r"^[•\-\*]\s*", "", line)

        if line.startswith("http"):
            cleaned_lines.append(line)
        elif "federalregister.gov" in line or "whitehouse.gov" in line:
            cleaned_lines.append(line)
        elif line.endswith(".csv") or "data/uploads/" in line or "data/web/" in line:
            continue
        elif not ("C:\\" in line or "/Users/" in line or "Desktop" in line):
            cleaned_lines.append(line)

    return "\n".join(f"• {line}" for line in cleaned_lines) if cleaned_lines else ""


def _split_answer_and_sources(text: str):
    m = re.split(r"\n\*\*Sources\*\*\n", text, maxsplit=1)
    if len(m) == 2:
        answer = m[0].strip()
        sources = _clean_sources(m[1])
        return answer, sources if sources else None
    return text.strip(), None


def _chunk(text: str, limit: int = 1900):
    text = text or ""
    for i in range(0, len(text), limit):
        yield text[i : i + limit]


def _title_for(query: str, answer_text: str | None = None) -> str:
    import re

    q = (query or "").strip()
    ql = q.lower()
    topics = [
        (r"\bgdpr\b", "GDPR"),
        (r"\bhipaa\b", "HIPAA"),
        (r"\bferpa\b", "FERPA"),
        (r"\bccpa\b|\bcpra\b", "CCPA/CPRA"),
        (r"\b(ai act|eu ai act)\b", "EU AI Act"),
        (r"\bsec\b|\bsecurities\b", "Securities Regulation"),
        (r"\bepa\b|\benvironment(al)?\b|\bregulations?\b", "EPA Regulations"),
        (r"\btelecom|fcc\b", "Telecom Policy"),
        (r"\btax\b", "Tax Policy"),
        (r"\bimmigration\b", "Immigration Policy"),
        (r"\bsection\s*230\b", "Section 230"),
        (r"\bexecutive order|eo\s*\d+|\border\s*\d{4,6}\b|14067\b", "Executive Orders"),
        (r"\bcompliance\b", "Compliance"),
        (r"\bprivacy|data protection\b", "Data Privacy"),
    ]
    for pat, title in topics:
        if re.search(pat, ql):
            return f"{title}: {q[:60]}"
    if re.search(r"\b(policy|policies|regulation|rule|law|statute|guidance)\b", ql):
        return f"Regulatory Q&A: {q[:60]}"
    return f"Answer: {q[:60] or 'Question'}"


def _answer_embed(
    answer_text: str, sources_text: Optional[str], title: str
) -> list[discord.Embed]:
    embeds: list[discord.Embed] = []
    desc = answer_text[:4096]
    e = discord.Embed(title=title, description=desc, color=0x18A999)
    e.set_footer(text="Policy Navigator • aiXplain agent + indexed sources")
    if sources_text:
        sources_field = (
            sources_text if len(sources_text) <= 1024 else sources_text[:1000] + "\n…"
        )
        e.add_field(name="Sources", value=sources_field, inline=False)
    embeds.append(e)
    remainder = answer_text[4096:]
    for chunk in _chunk(remainder):
        embeds.append(discord.Embed(description=chunk, color=0x18A999))
    return embeds


def _session_id_from_interaction(ix: discord.Interaction) -> str:
    ch = ix.channel
    if isinstance(ch, discord.DMChannel) or getattr(ch, "guild", None) is None:
        return f"user-{ix.user.id}-dm-{ch.id}"
    return f"guild-{ch.guild.id}-channel-{ch.id}"


def _session_id_from_message(msg: discord.Message) -> str:
    ch = msg.channel
    if isinstance(ch, discord.DMChannel) or getattr(ch, "guild", None) is None:
        return f"user-{msg.author.id}-dm-{ch.id}"
    return f"guild-{ch.guild.id}-channel-{ch.id}"


intents = discord.Intents.default()
intents.message_content = True


class PolicyClient(discord.Client):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        if GUILD:
            self.tree.copy_global_to(guild=GUILD)
            cmds = await self.tree.sync(guild=GUILD)
            print(f"Synced {len(cmds)} slash command(s) to guild {GUILD.id}.")
        else:
            cmds = await self.tree.sync()
            print(f"Synced {len(cmds)} global slash command(s).")


client = PolicyClient(intents=intents)


@client.event
async def on_ready():
    print(f"Logged in as {client.user} (id: {client.user.id})")
    await client.change_presence(
        activity=discord.Game(name=f"{PREFIX} <your question>")
    )


@client.event
async def on_guild_join(guild: discord.Guild):
    try:
        cmds = await client.tree.sync(guild=discord.Object(id=guild.id))
        print(f"Synced {len(cmds)} slash command(s) to new guild {guild.id}.")
    except Exception as e:
        print(f"Sync failed on join {guild.id}: {e}")


@client.tree.command(name="ask", description="Ask the Policy Navigator agent.")
@app_commands.describe(query="Your question")
async def slash_ask(interaction: discord.Interaction, query: str):
    await interaction.response.defer(thinking=True)
    loop = asyncio.get_running_loop()
    session_id = _session_id_from_interaction(interaction)
    try:
        result = await loop.run_in_executor(
            None, partial(answer, query, session_id=session_id)
        )
        final_text = _to_text(result)
    except Exception as e:
        final_text = f"Sorry, something went wrong: {e}"

    body, sources = _split_answer_and_sources(final_text)
    title = _title_for(query, body)
    embeds = _answer_embed(body, sources, title=title)
    await interaction.followup.send(embed=embeds[0])
    for e in embeds[1:]:
        await interaction.followup.send(embed=e)


@client.tree.command(name="add", description="Add a URL or upload a file to the index.")
@app_commands.describe(
    url="Public URL to ingest (HTML will be fetched)", file="File to upload and index"
)
async def slash_add(
    interaction: discord.Interaction,
    url: Optional[str] = None,
    file: Optional[discord.Attachment] = None,
):
    await interaction.response.defer(thinking=True, ephemeral=True)
    loop = asyncio.get_running_loop()
    msgs: list[str] = []

    if url:
        try:
            res = await loop.run_in_executor(None, partial(ingest_url, url))
            msgs.append(res)
        except Exception as e:
            msgs.append(f"Add URL failed: {e}")

    if file:
        try:
            data = await file.read()
            res = await loop.run_in_executor(
                None, partial(ingest_file_bytes, file.filename, data)
            )
            msgs.append(res)
        except Exception as e:
            msgs.append(f"Add file failed: {e}")

    if not msgs:
        await interaction.followup.send(
            "Provide a `url` and/or `file`.", ephemeral=True
        )
        return

    await interaction.followup.send("\n".join(msgs), ephemeral=True)


@client.tree.command(
    name="reset_history", description="Clear conversation memory for this channel/DM."
)
async def slash_reset_history(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    session_id = _session_id_from_interaction(interaction)
    try:
        memory.clear(session_id)
        await interaction.followup.send(
            "History cleared for this channel/DM.", ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(f"Couldn't clear history: {e}", ephemeral=True)


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    content = (message.content or "").strip()
    if not content.lower().startswith(PREFIX):
        return

    query = content[len(PREFIX) :].strip()
    if not query:
        await message.reply(f"Usage: `{PREFIX} your question…`")
        return

    async with message.channel.typing():
        loop = asyncio.get_running_loop()
        session_id = _session_id_from_message(message)
        try:
            result = await loop.run_in_executor(
                None, partial(answer, query, session_id=session_id)
            )
            final_text = _to_text(result)
        except Exception as e:
            final_text = f"Sorry, something went wrong: {e}"

    body, sources = _split_answer_and_sources(final_text)
    title = _title_for(query, body)
    embeds = _answer_embed(body, sources, title=title)
    msg = await message.reply(embed=embeds[0])
    for e in embeds[1:]:
        await message.channel.send(embed=e, reference=msg)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN not set in .env")
    client.run(TOKEN)
