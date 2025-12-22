from word2number import w2n


def safe_word_to_num(text: str) -> int | None:
	text = (text or "").strip().lower()
	if not text:
		return None
	try:
		return int(text)
	except ValueError:
		pass
	try:
		return int(w2n.word_to_num(text))
	except (ValueError, TypeError):
		return None