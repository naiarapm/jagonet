import argparse
import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress

import requests
from bs4 import BeautifulSoup, Tag
from tqdm import tqdm


def extract_seed_urls(root_url: str) -> list[str]:
    response = requests.get(root_url)
    soup = BeautifulSoup(response.text, 'html.parser')
    seed_urls = [a_tag['href'] for a_tag in soup.select('#searchContent .col-md-6:first-child .zerrenda-gaiak li.gaia-2 a')]
    return seed_urls


def extract_target_urls(seed_url: str) -> set[str]:
    target_urls = set()
    page = 0
    while True:
        page_url = f"{seed_url}&nondik={page}"
        response = requests.get(page_url)
        soup = BeautifulSoup(response.text, 'html.parser')
        more_urls = []
        for a_tag in soup.select('#searchContent h3 a'):
            with suppress(KeyError):
                more_urls.append(a_tag['href'])
        if not more_urls:
            break
        target_urls.update(more_urls)
        page += 10
    return target_urls


def get_document(target_url: str) -> dict:

    response = requests.get(target_url)
    soup = BeautifulSoup(response.text, 'html.parser')
    content = soup.find(id='searchContent')

    id_ = int(target_url.split('=')[-1])
    title = get_text(content.find('h3'))

    question = '\n'.join(get_text(par) for par in content.find(class_='jagonet-galdera2').find('p').findAll('p', recursive=False))
    answer = '\n'.join(get_text(par) for par in content.find(class_='jagonet-erantzuna2').findAll('p', recursive=False))

    try:
        extra = {get_text(a_tag).strip('"'): a_tag.get('href') for a_tag in content.find(class_='jagonet-infoplus').findAll('a')}
    except AttributeError:
        extra = None

    tags = content.findAll(class_='jagonet-gehigarria-gaiak')
    question_type = get_text(tags[0]).split(', ')
    unit_type = get_text(tags[-1]).split(', ')

    document = dict(
        id=id_,
        url=target_url,
        title=title,
        question=question,
        answer=answer,
        extra=extra,
        question_type=question_type,
        unit_type=unit_type
    )

    return document


def get_text(tag: Tag) -> str:
    parts = []
    tag_iter = iter(tag.descendants)
    with suppress(StopIteration):
        while True:
            desc = next(tag_iter)
            if not desc:
                continue
            # ordinary text
            if isinstance(desc, str):
                desc = desc.replace('\t', '').replace('\n', '')
                if desc:
                    parts.append(desc)
            # usually a metalinguistic reference; we want to keep the annotation
            elif desc.name == 'em':
                if not desc.text.strip():
                    continue
                parts.append(str(desc))
                next(tag_iter)
            # a metalinguistic reference; we want to keep the annotation
            elif 'jagonet-adibidea' in desc.get('class', []):
                if not desc.text.strip():
                    continue
                # just for the sake of readability
                desc.name = 'adib'
                del desc['class']
                parts.append(str(desc))
                next(tag_iter)
    text = ''.join(parts)
    # minimum normalization
    text = text.replace(' ', '').replace('  ', ' ')
    text = re.sub(r'(\S)<([^/>]+)> ', r'\1 <\2>', text)
    text = re.sub(r' </([^>]+)>(\S)', r'</\1> \2', text)
    text = html.unescape(text)
    return text


def main(root_url: str, output_path: str, max_workers: int, dump_csv: bool = False):

    documents = {}
    seed_urls = extract_seed_urls(root_url)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for seed_url in seed_urls:
            target_urls = [x for x in extract_target_urls(seed_url) if x not in documents]
            results = zip(target_urls, tqdm(executor.map(get_document, target_urls), total=len(target_urls)))
            documents.update(results)
    documents = sorted(documents.values(), key=lambda d: d['id'])

    with open(output_path, mode='w', encoding='utf8') as wf:
        for document in documents:
            wf.write(json.dumps(document) + '\n')

    if dump_csv:
        with open(output_path.rsplit('.', maxsplit=1)[0] + '.csv', mode='w', newline='', encoding='utf8') as wf:
            fieldnames = ['id', 'url', 'title', 'question', 'answer', 'extra', 'question_type', 'unit_type']
            csv_writer = csv.DictWriter(wf, fieldnames=fieldnames)
            csv_writer.writeheader()
            csv_writer.writerows(documents)


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description='Download JAGONET Q&A from the web')

    parser.add_argument('--root_url', default='https://www.euskaltzaindia.eus/index.php?option=com_jagonet&task=gaiak', help='Specify the root URL.')
    parser.add_argument('--output_path', default='./jagonet.jsonl', help='Specify the output file path.')
    parser.add_argument('--max_workers', type=int, default=16, help='Specify the number of workers.')
    parser.add_argument('--dump_csv', action='store_true', help='Specify whether to dump the data as a CSV file, in addition to the JSONLines file.')

    args = parser.parse_args()

    main(args.root_url, args.output_path, args.max_workers, dump_csv=args.dump_csv)
