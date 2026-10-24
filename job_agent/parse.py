"""Parse observed public job content without guessing missing attributes."""
import json
import re
from urllib.parse import urljoin, urlsplit, unquote, parse_qs

from bs4 import BeautifulSoup
import phonenumbers


def soup_for(html):
    soup = BeautifulSoup(html, 'html.parser')
    for node in soup(['script', 'style', 'noscript']):
        node.decompose()
    return soup


def extract_contacts(html, source_url, region='PK'):
    soup = soup_for(html)
    text = soup.get_text(' ', strip=True)
    emails = set(re.findall(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', text, re.I))
    phone_texts = re.findall(r'\+\d[\d ()-]{6,}\d', text)
    phone_texts.extend(re.findall(
        r'\b(?:call|phone|telephone|tel|mobile|whatsapp)\s*[:.\-]?\s*(\+?[\d(][\d ()-]{6,}\d)', text, re.I))
    for a in soup.select('a[href]'):
        href = unquote(a['href'])
        if href.lower().startswith('mailto:'):
            emails.update(re.findall(r'[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}', href[7:].split('?')[0], re.I))
        elif href.lower().startswith('tel:'):
            phone_texts.append(href[4:].split('?')[0])
    phones = set()
    for text in phone_texts:
        for match in phonenumbers.PhoneNumberMatcher(text, region):
            if phonenumbers.is_valid_number(match.number):
                phones.add(phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164))
    return [dict(kind=kind, value=value, source_url=source_url)
            for kind, values in [('email', sorted({e.lower() for e in emails})), ('phone', sorted(phones))]
            for value in values]


def linkedin_id(url):
    parsed = urlsplit(url)
    if not (parsed.hostname == 'linkedin.com' or (parsed.hostname or '').endswith('.linkedin.com')):
        return None
    match = re.search(r'/jobs/view/(?:[^/?]*-)?(\d+)(?:/|$)', parsed.path)
    return match.group(1) if match else None


def parse_search(html):
    ids = []
    soup = BeautifulSoup(html, 'html.parser')
    for a in soup.select('a[href]'):
        job_id = linkedin_id(urljoin('https://www.linkedin.com', a['href']))
        if job_id and job_id not in ids:
            ids.append(job_id)
    return [f'https://www.linkedin.com/jobs/view/{job_id}' for job_id in ids]


def structured_job(soup):
    def walk(value):
        if isinstance(value, list):
            for item in value:
                yield from walk(item)
        elif isinstance(value, dict):
            types = value.get('@type', [])
            if types == 'JobPosting' or isinstance(types, list) and 'JobPosting' in types:
                yield value
            if '@graph' in value:
                yield from walk(value['@graph'])
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            for value in walk(json.loads(node.string or node.get_text())):
                return value
        except (ValueError, TypeError):
            continue
    return {}


def external_links(soup, base):
    result = []
    for a in soup.select('a[href]'):
        url = urljoin(base, a['href'])
        parsed = urlsplit(url)
        if (parsed.hostname == 'linkedin.com' or (parsed.hostname or '').endswith('.linkedin.com')) and (
            parsed.path == '/redir/redirect' or parsed.path.startswith('/jobs/view/externalApply/')
        ):
            url = parse_qs(parsed.query).get('url', [''])[0]
            parsed = urlsplit(url)
        if parsed.scheme in ('http', 'https') and parsed.hostname and not (
            parsed.hostname == 'linkedin.com' or parsed.hostname.endswith('.linkedin.com')
        ):
            if url not in result:
                result.append(url)
    return result


def parse_job(html, url, region='PK'):
    soup = BeautifulSoup(html, 'html.parser')
    meta = structured_job(soup)
    def text(selector):
        node = soup.select_one(selector)
        return node.get_text(' ', strip=True) if node else ''
    description = soup.select_one('.show-more-less-html__markup')
    if description is None:
        description = soup.select_one('.description__text, #job-details')
    description_html = str(description) if description else meta.get('description', '')
    if not isinstance(description_html, str):
        description_html = ''
    org = meta.get('hiringOrganization') or {}
    if not isinstance(org, dict):
        org = {}
    location = meta.get('jobLocation') or {}
    if isinstance(location, list):
        location = location[0] if location else {}
    address = location.get('address', {}) if isinstance(location, dict) else {}
    location_text = ', '.join(str(address[k]) for k in ['addressLocality', 'addressRegion', 'addressCountry'] if address.get(k)) if isinstance(address, dict) else str(address)
    criteria = {}
    for item in soup.select('.description__job-criteria-item'):
        label, value = item.select_one('h3'), item.select_one('span')
        if label and value:
            criteria[label.get_text(' ', strip=True)] = value.get_text(' ', strip=True)
    recruiters = []
    for a in soup.select('.message-the-recruiter a[href*="/in/"], .hirer-card a[href*="/in/"]'):
        recruiters.append({'name': a.get_text(' ', strip=True), 'url': urljoin(url, a['href']).split('?')[0]})
    job_id = linkedin_id(url)
    if not job_id:
        raise ValueError('Expected a LinkedIn /jobs/view/<id> URL')
    title = text('h1.top-card-layout__title, h2.top-card-layout__title, h1') or meta.get('title', '')
    if not title or not description_html:
        raise ValueError('Page has no job title or description; it may be blocked or its layout changed')
    links = external_links(soup, url)
    company_link = soup.select_one('.topcard__org-name-link[href], .job-details-jobs-unified-top-card__company-name a[href]')
    date_node = soup.select_one('time[datetime]')
    return {
        'job_id': job_id, 'url': f'https://www.linkedin.com/jobs/view/{job_id}',
        'title': title, 'company': text('.topcard__org-name-link, .job-details-jobs-unified-top-card__company-name') or org.get('name', ''),
        'company_url': org.get('sameAs', '') or (urljoin(url, company_link['href']).split('?')[0] if company_link else ''),
        'location': text('.topcard__flavor--bullet') or location_text,
        'description': soup_for(description_html).get_text('\n', strip=True),
        'description_html': description_html, 'date_posted': meta.get('datePosted', '') or (date_node['datetime'] if date_node else ''),
        'posted_text': text('.posted-time-ago__text'),
        'applicants_text': text('.num-applicants__caption, .num-applicants__figure'),
        'valid_through': meta.get('validThrough', ''), 'salary': meta.get('baseSalary') or text('.salary, .compensation__salary'),
        'criteria': criteria, 'recruiters': recruiters, 'external_links': links,
        'metadata': meta, 'contacts': extract_contacts(description_html, url, region),
        'enrichment': [],
    }
