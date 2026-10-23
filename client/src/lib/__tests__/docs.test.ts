import { readFileSync } from 'fs';
import { join } from 'path';
import { DOC_PAGES, searchDocs } from '../docs';

describe('docs index', () => {
  it.each(DOC_PAGES.map((p) => [p.href, p] as const))('%s has a section for every index entry', (href, page) => {
    const source = readFileSync(join(__dirname, '../../app', href, 'page.tsx'), 'utf8');
    for (const section of page.sections) {
      expect(source).toContain(`id="${section.id}"`);
    }
  });

  it('finds sections by title and keywords', () => {
    expect(searchDocs('checksum')[0]).toMatchObject({ href: '/docs/providers#install-release' });
    expect(searchDocs('streaming').map((h) => h.href)).toContain('/docs/api#streaming');
    expect(searchDocs('nothing-matches-this')).toEqual([]);
    expect(searchDocs('  ')).toEqual([]);
  });
});
