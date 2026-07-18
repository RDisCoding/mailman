from metrics_logger import summarize_performance
from ga4_collector  import compute_ga4_delta
from report_mailer  import build_report_html
print('All imports: OK')

perf = summarize_performance(days=3)
ga4  = compute_ga4_delta(days=3)
html = build_report_html(perf, ga4)
print(f'Report HTML built: {len(html)} chars')
print(f'Stats: sent={perf["total_sent"]} opens={perf["total_opens"]} rate={perf["avg_open_rate"]:.1%}')
print(f'GA4:   users={ga4["total_new_users"]} installs={ga4["total_installs"]}')
print('All good.')
