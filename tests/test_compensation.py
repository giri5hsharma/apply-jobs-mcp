from apply_jobs_mcp.compensation import parse_compensation


def test_inr_monthly():
    c = parse_compensation("Rs 25,000/month")
    assert c.per_month_inr == 25000
    assert c.currency == "INR"


def test_lpa():
    c = parse_compensation("Rs 3 LPA")
    assert c.per_month_inr == 25000  # 3 lakh per year / 12


def test_annual_inr():
    c = parse_compensation("INR 1200000 per annum")
    assert c.per_month_inr == 100000


def test_usd_monthly_converted():
    c = parse_compensation("$2,000/month", usd_to_inr=84)
    assert c.per_month_inr == 168000
    assert c.currency == "USD"


def test_range_uses_lower_bound():
    c = parse_compensation("20-25K / month")
    assert c.per_month_inr == 20000


def test_hourly():
    c = parse_compensation("$50/hour", usd_to_inr=84)
    assert c.per_month_inr == round(50 * 8 * 21 * 84)


def test_unknown_returns_none():
    c = parse_compensation("Competitive salary")
    assert c.per_month_inr is None


def test_unpaid_is_zero():
    c = parse_compensation("Unpaid internship")
    assert c.per_month_inr == 0


def test_stipend_keyword_defaults_to_month():
    c = parse_compensation("Stipend: Rs 30000")
    assert c.per_month_inr == 30000
