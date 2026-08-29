const { test, expect } = require('@playwright/test');
const fs = require('fs');
const http = require('http');
const os = require('os');
const path = require('path');
const { spawn, spawnSync } = require('child_process');

const repoRoot = path.resolve(__dirname, '..', '..');

function runPython(args, options = {}) {
  const result = spawnSync('python', args, {
    cwd: repoRoot,
    encoding: 'utf8',
    ...options,
  });
  return result;
}

function runCommand(command, args, options = {}) {
  return spawnSync(command, args, {
    cwd: repoRoot,
    encoding: 'utf8',
    ...options,
  });
}

function runPythonAsync(args, options = {}) {
  return new Promise((resolve) => {
    const child = spawn('python', args, {
      cwd: repoRoot,
      ...options,
    });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString();
    });
    child.on('close', (status) => {
      resolve({ status, stdout, stderr });
    });
  });
}

function makeTempDir(name) {
  return fs.mkdtempSync(path.join(os.tmpdir(), `pdfrejuvenator-${name}-`));
}

function copyProjectForInstall(destination) {
  fs.cpSync(repoRoot, destination, {
    recursive: true,
    filter: (source) => {
      const relative = path.relative(repoRoot, source);
      if (!relative) {
        return true;
      }
      const parts = relative.split(path.sep);
      return !parts.some((part) => (
        part === '.git'
        || part === '.ruff_cache'
        || part === '__pycache__'
        || part === 'build'
        || part === 'node_modules'
        || part === 'pdfrejuvenator.egg-info'
        || part === 'playwright-report'
        || part === 'test-results'
      ));
    },
  });
}

function writeSearchIndex(tempDir) {
  const sentinel = 'PDFREJUVENATOR_SENTINEL_PRIVATE_TEXT';
  const records = [
    {
      schema_version: 'pdfrejuvenator.search_record.v0.4',
      record_id: 'synthetic-bridge-001',
      record_type: 'text',
      page: 4,
      artifact_path: 'synthetic/source.md',
      text: `The city engineer validates the north bridge with calibrated sensor evidence. ${sentinel}`,
      metadata: { title: 'Bridge validation note' },
    },
    {
      schema_version: 'pdfrejuvenator.search_record.v0.4',
      record_id: 'synthetic-harbor-002',
      record_type: 'text',
      page: 9,
      artifact_path: 'synthetic/source.md',
      text: 'The harbor pump report documents a stable overnight pressure reading.',
      metadata: { title: 'Harbor pump note' },
    },
    {
      schema_version: 'pdfrejuvenator.search_record.v0.4',
      record_id: 'synthetic-garden-003',
      record_type: 'text',
      page: 12,
      artifact_path: 'synthetic/source.md',
      text: 'The garden gate checklist records a missing hinge pin.',
      metadata: { title: 'Garden gate note' },
    },
  ];
  const searchIndex = path.join(tempDir, 'synthetic_search_index.jsonl');
  fs.writeFileSync(searchIndex, records.map((record) => JSON.stringify(record)).join('\n') + '\n', 'utf8');
  return { searchIndex, sentinel };
}

function buildVectorIndex(tempDir, options = {}) {
  const { searchIndex, sentinel } = writeSearchIndex(tempDir);
  const vectorIndex = path.join(tempDir, options.omitText ? 'synthetic_vector_index_omit_text.json' : 'synthetic_vector_index.json');
  const args = [
    '-m',
    'pdfrejuvenator',
    'build-vector-index',
    searchIndex,
    '--output',
    vectorIndex,
    '--provider',
    'deterministic-test',
    '--max-chars',
    '400',
  ];
  if (options.omitText) {
    args.push('--omit-text');
  }
  const result = runPython(args);
  expect(result.status, result.stderr || result.stdout).toBe(0);
  return { searchIndex, vectorIndex, sentinel };
}

function parseJsonlWithoutSummary(stdout) {
  return stdout
    .split(/\r?\n/)
    .filter((line) => line.trim().startsWith('{'))
    .map((line) => JSON.parse(line));
}

test('retrieval api returns ranked evidence through vector-search', () => {
  const tempDir = makeTempDir('retrieval');
  const { vectorIndex } = buildVectorIndex(tempDir);

  const result = runPython([
    '-m',
    'pdfrejuvenator',
    'vector-search',
    vectorIndex,
    'bridge sensor evidence',
    '--provider',
    'deterministic-test',
    '--limit',
    '2',
  ]);

  expect(result.status, result.stderr || result.stdout).toBe(0);
  const records = parseJsonlWithoutSummary(result.stdout);
  expect(records).toHaveLength(2);
  expect(records[0].score).toBeGreaterThanOrEqual(records[1].score);
  for (const record of records) {
    expect(record.source_id).toBeTruthy();
    expect(record.source_record_id).toBeTruthy();
    expect(record.chunk_id).toBeTruthy();
    expect(typeof record.score).toBe('number');
    expect(record.text).toBeTruthy();
  }
});

test('redacted retrieval does not emit text', () => {
  const tempDir = makeTempDir('redacted');
  const { vectorIndex, sentinel } = buildVectorIndex(tempDir, { omitText: true });

  const result = runPython([
    '-m',
    'pdfrejuvenator',
    'vector-search',
    vectorIndex,
    'bridge sensor evidence',
    '--provider',
    'deterministic-test',
    '--limit',
    '2',
    '--hide-text',
  ]);

  expect(result.status, result.stderr || result.stdout).toBe(0);
  expect(result.stdout).not.toContain(sentinel);
  const records = parseJsonlWithoutSummary(result.stdout);
  expect(records).toHaveLength(2);
  for (const record of records) {
    expect(record.source_id).toBeTruthy();
    expect(record.chunk_id).toBeTruthy();
    expect(record).not.toHaveProperty('text');
  }
});

test('answer schema validator accepts grounded answer and rejects missing citation', () => {
  const tempDir = makeTempDir('validator');
  const evidencePath = path.join(tempDir, 'evidence.jsonl');
  const answerPath = path.join(tempDir, 'answer.json');
  const evidence = {
    chunk_id: 'synthetic-bridge-001::chunk0000',
    source_id: 'synthetic-bridge-001',
    source_record_id: 'synthetic-bridge-001',
    score: 0.88,
    text: 'The city engineer validates the bridge.',
  };
  const answer = {
    schema_version: 'pdfrejuvenator.answer_query.v0.7',
    question: 'Who validates the bridge?',
    answer: 'The city engineer validates the bridge.',
    confidence: 'high',
    citations: [
      {
        claim: 'The city engineer validates the bridge.',
        source_id: 'synthetic-bridge-001',
        chunk_id: 'synthetic-bridge-001::chunk0000',
        score: 0.88,
      },
    ],
    unsupported_claims: [],
    evidence_count: 1,
    insufficient_evidence: false,
  };
  fs.writeFileSync(evidencePath, `${JSON.stringify(evidence)}\n`, 'utf8');
  fs.writeFileSync(answerPath, JSON.stringify(answer), 'utf8');

  const valid = runPython(['scripts\\validate_answer_query.py', answerPath, evidencePath]);
  expect(valid.status, valid.stderr || valid.stdout).toBe(0);

  answer.citations[0].chunk_id = 'missing-chunk';
  fs.writeFileSync(answerPath, JSON.stringify(answer), 'utf8');
  const invalid = runPython(['scripts\\validate_answer_query.py', answerPath, evidencePath]);
  expect(invalid.status).not.toBe(0);
  expect(invalid.stdout).toContain('chunk_id does not reference retrieved evidence');
});

test('answer-query without llm returns grounded packet', () => {
  const tempDir = makeTempDir('no-generate');
  const { vectorIndex } = buildVectorIndex(tempDir);
  const answerPath = path.join(tempDir, 'answer_query.json');
  const evidencePath = path.join(tempDir, 'answer_query_evidence.jsonl');

  const result = runPython([
    '-m',
    'pdfrejuvenator',
    'answer-query',
    vectorIndex,
    'Who validates the north bridge?',
    '--provider',
    'deterministic-test',
    '--limit',
    '2',
    '--no-generate',
    '--output',
    answerPath,
    '--evidence-output',
    evidencePath,
  ]);

  expect(result.status, result.stderr || result.stdout).toBe(0);
  const answer = JSON.parse(fs.readFileSync(answerPath, 'utf8'));
  expect(answer.schema_version).toBe('pdfrejuvenator.answer_query.v0.7');
  expect(answer.evidence_count).toBeGreaterThan(0);
  expect(answer.citations.length).toBe(answer.evidence_count);
  expect(answer.answer).toContain('Generation provider not enabled');

  const validation = runPython(['scripts\\validate_answer_query.py', answerPath, evidencePath]);
  expect(validation.status, validation.stderr || validation.stdout).toBe(0);

  const consumed = runPython([
    'scripts\\assert_answer_query_output.py',
    answerPath,
    evidencePath,
    '--expected-question',
    'Who validates the north bridge?',
    '--expected-fact',
    'city engineer validates the north bridge',
    '--expected-evidence-count',
    '2',
    '--expected-page',
    '4',
    '--expected-doc-id',
    '',
  ]);
  expect(consumed.status, consumed.stderr || consumed.stdout).toBe(0);
});

test('installed console script answer-query returns grounded packet', () => {
  const tempDir = makeTempDir('console-script');
  const venvDir = path.join(tempDir, '.venv');
  const { vectorIndex } = buildVectorIndex(tempDir);
  const answerPath = path.join(tempDir, 'console_answer_query.json');
  const evidencePath = path.join(tempDir, 'console_answer_query_evidence.jsonl');

  let result = runPython(['-m', 'venv', '--system-site-packages', venvDir]);
  expect(result.status, result.stderr || result.stdout).toBe(0);

  const projectCopy = path.join(tempDir, 'project-copy');
  copyProjectForInstall(projectCopy);

  const pythonExe = path.join(venvDir, 'Scripts', 'python.exe');
  const consoleExe = path.join(venvDir, 'Scripts', 'pdfrejuvenator.exe');
  result = runCommand(pythonExe, ['-m', 'pip', 'install', '--no-deps', projectCopy]);
  expect(result.status, result.stderr || result.stdout).toBe(0);
  expect(fs.existsSync(consoleExe)).toBe(true);

  result = runCommand(consoleExe, [
    'answer-query',
    vectorIndex,
    'Who validates the north bridge?',
    '--provider',
    'deterministic-test',
    '--limit',
    '1',
    '--no-generate',
    '--output',
    answerPath,
    '--evidence-output',
    evidencePath,
    '--pretty',
  ]);

  expect(result.status, result.stderr || result.stdout).toBe(0);
  expect(result.stdout).toContain('ANSWER QUERY SUMMARY: evidence=1 failures=0');

  const answer = JSON.parse(fs.readFileSync(answerPath, 'utf8'));
  const evidence = JSON.parse(fs.readFileSync(evidencePath, 'utf8').trim());

  expect(answer.schema_version).toBe('pdfrejuvenator.answer_query.v0.7');
  expect(answer.question).toBe('Who validates the north bridge?');
  expect(answer.evidence_count).toBe(1);
  expect(answer.insufficient_evidence).toBe(false);
  expect(answer.citations).toHaveLength(1);
  expect(answer.citations[0].chunk_id).toBe(evidence.chunk_id);
  expect(answer.citations[0].source_id).toBe(evidence.source_id);
  expect(answer.citations[0].page).toBe(evidence.page);
  expect(evidence.metadata.title).toBe('Bridge validation note');
  expect(evidence.text).toContain('city engineer validates the north bridge');
});

test('installed console script answer-query fails closed on invalid inputs', () => {
  const tempDir = makeTempDir('console-script-negative');
  const venvDir = path.join(tempDir, '.venv');
  const { vectorIndex } = buildVectorIndex(tempDir);
  const malformedIndex = path.join(tempDir, 'malformed_vector_index.json');
  const malformedAnswer = path.join(tempDir, 'malformed_answer_query.json');
  const malformedEvidence = path.join(tempDir, 'malformed_answer_query_evidence.jsonl');
  const providerAnswer = path.join(tempDir, 'provider_failure_answer_query.json');
  const providerEvidence = path.join(tempDir, 'provider_failure_answer_query_evidence.jsonl');

  let result = runPython(['-m', 'venv', '--system-site-packages', venvDir]);
  expect(result.status, result.stderr || result.stdout).toBe(0);

  const projectCopy = path.join(tempDir, 'project-copy');
  copyProjectForInstall(projectCopy);

  const pythonExe = path.join(venvDir, 'Scripts', 'python.exe');
  const consoleExe = path.join(venvDir, 'Scripts', 'pdfrejuvenator.exe');
  result = runCommand(pythonExe, ['-m', 'pip', 'install', '--no-deps', projectCopy]);
  expect(result.status, result.stderr || result.stdout).toBe(0);
  expect(fs.existsSync(consoleExe)).toBe(true);

  fs.writeFileSync(
    malformedIndex,
    JSON.stringify({ schema_version: 'pdfrejuvenator.vector_index.v0.7', chunks: 'not-a-list' }),
    'utf8',
  );
  result = runCommand(consoleExe, [
    'answer-query',
    malformedIndex,
    'Who validates the north bridge?',
    '--provider',
    'deterministic-test',
    '--no-generate',
    '--output',
    malformedAnswer,
    '--evidence-output',
    malformedEvidence,
  ]);
  expect(result.status).not.toBe(0);
  expect(result.stderr).toContain('chunks must be a list');
  expect(fs.existsSync(malformedAnswer)).toBe(false);
  expect(fs.existsSync(malformedEvidence)).toBe(false);

  result = runCommand(consoleExe, [
    'answer-query',
    vectorIndex,
    'Who validates the north bridge?',
    '--provider',
    'deterministic-test',
    '--answer-provider',
    'ollama',
    '--answer-model',
    'mock-model',
    '--hide-evidence-text',
    '--output',
    providerAnswer,
    '--evidence-output',
    providerEvidence,
  ]);
  expect(result.status).toBe(1);
  expect(result.stderr).toContain('generated answers require evidence text');
  expect(fs.existsSync(providerAnswer)).toBe(false);
  expect(fs.existsSync(providerEvidence)).toBe(false);
});

test('answer-query no-generate redacted output does not copy evidence text', () => {
  const tempDir = makeTempDir('no-generate-redacted');
  const { vectorIndex, sentinel } = buildVectorIndex(tempDir);
  const answerPath = path.join(tempDir, 'answer_query.json');
  const evidencePath = path.join(tempDir, 'answer_query_evidence.jsonl');

  const result = runPython([
    '-m',
    'pdfrejuvenator',
    'answer-query',
    vectorIndex,
    'Who validates the north bridge?',
    '--provider',
    'deterministic-test',
    '--limit',
    '1',
    '--no-generate',
    '--hide-evidence-text',
    '--output',
    answerPath,
    '--evidence-output',
    evidencePath,
  ]);

  expect(result.status, result.stderr || result.stdout).toBe(0);
  const redacted = runPython([
    'scripts\\assert_redacted_answer_query_output.py',
    answerPath,
    evidencePath,
    '--forbidden-text',
    sentinel,
  ]);
  expect(redacted.status, redacted.stderr || redacted.stdout).toBe(0);
  expect(redacted.stdout).toContain('REDACTED ANSWER ASSERTIONS: checks=10 failures=0');
});

test('answer-query on empty vector index returns insufficient evidence', () => {
  const tempDir = makeTempDir('empty-vector');
  const searchIndex = path.join(tempDir, 'empty_search_index.jsonl');
  const vectorIndex = path.join(tempDir, 'empty_vector_index.json');
  const answerPath = path.join(tempDir, 'answer_query.json');
  const evidencePath = path.join(tempDir, 'answer_query_evidence.jsonl');
  fs.writeFileSync(searchIndex, '', 'utf8');

  const build = runPython([
    '-m',
    'pdfrejuvenator',
    'build-vector-index',
    searchIndex,
    '--output',
    vectorIndex,
    '--provider',
    'deterministic-test',
  ]);
  expect(build.status, build.stderr || build.stdout).toBe(0);

  const result = runPython([
    '-m',
    'pdfrejuvenator',
    'answer-query',
    vectorIndex,
    'What does the missing evidence say?',
    '--provider',
    'deterministic-test',
    '--no-generate',
    '--output',
    answerPath,
    '--evidence-output',
    evidencePath,
  ]);
  expect(result.status, result.stderr || result.stdout).toBe(0);
  const answer = JSON.parse(fs.readFileSync(answerPath, 'utf8'));
  expect(answer.evidence_count).toBe(0);
  expect(answer.insufficient_evidence).toBe(true);
  expect(answer.citations).toHaveLength(0);

  const validation = runPython(['scripts\\validate_answer_query.py', answerPath, evidencePath]);
  expect(validation.status, validation.stderr || validation.stdout).toBe(0);
});

test('answer-query fails closed on malformed vector indexes', () => {
  const tempDir = makeTempDir('malformed-vector-index');
  const result = runPython([
    'scripts\\assert_malformed_vector_index.py',
    '--output-dir',
    tempDir,
  ]);

  expect(result.status, result.stderr || result.stdout).toBe(0);
  expect(result.stdout).toContain('MALFORMED VECTOR INDEX ASSERTIONS: checks=6 failures=0');
});

test('answer-query with mock ollama returns valid grounded answer', async () => {
  const tempDir = makeTempDir('mock-ollama');
  const { vectorIndex } = buildVectorIndex(tempDir);
  const answerPath = path.join(tempDir, 'answer_query.json');
  const evidencePath = path.join(tempDir, 'answer_query_evidence.jsonl');
  let requestCount = 0;

  const server = http.createServer((request, response) => {
    requestCount += 1;
    let body = '';
    request.on('data', (chunk) => {
      body += chunk.toString();
    });
    request.on('end', () => {
      const requestPayload = JSON.parse(body);
      const prompt = requestPayload.messages.find((message) => message.role === 'user').content;
      const chunkId = prompt.match(/"chunk_id":"([^"]+)"/)?.[1] || prompt.match(/"chunk_id": "([^"]+)"/)?.[1];
      const sourceId = prompt.match(/"source_id":"([^"]+)"/)?.[1] || prompt.match(/"source_id": "([^"]+)"/)?.[1];
      const answer = {
        schema_version: 'pdfrejuvenator.answer_query.v0.7',
        question: 'Who validates the north bridge?',
        answer: 'The city engineer validates the north bridge.',
        confidence: 'high',
        citations: [
          {
            claim: 'The city engineer validates the north bridge.',
            source_id: sourceId,
            chunk_id: chunkId,
            score: 0.9,
            record_type: 'text',
          },
        ],
        unsupported_claims: [],
        evidence_count: 2,
        insufficient_evidence: false,
      };
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ message: { content: JSON.stringify(answer) } }));
    });
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;

  try {
    const result = await runPythonAsync([
      '-m',
      'pdfrejuvenator',
      'answer-query',
      vectorIndex,
      'Who validates the north bridge?',
      '--provider',
      'deterministic-test',
      '--limit',
      '2',
      '--answer-provider',
      'ollama',
      '--answer-model',
      'mock-model',
      '--ollama-url',
      `http://127.0.0.1:${port}`,
      '--output',
      answerPath,
      '--evidence-output',
      evidencePath,
    ]);

    expect(result.status, result.stderr || result.stdout).toBe(0);
    expect(requestCount).toBe(1);
    const validation = runPython(['scripts\\validate_answer_query.py', answerPath, evidencePath]);
    expect(validation.status, validation.stderr || validation.stdout).toBe(0);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test('answer-query rejects mock ollama citation outside evidence', async () => {
  const tempDir = makeTempDir('mock-ollama-negative');
  const { vectorIndex } = buildVectorIndex(tempDir);
  const answerPath = path.join(tempDir, 'answer_query.json');

  const server = http.createServer((_request, response) => {
    const answer = {
      schema_version: 'pdfrejuvenator.answer_query.v0.7',
      question: 'Who validates the north bridge?',
      answer: 'The city engineer validates the north bridge.',
      confidence: 'high',
      citations: [
        {
          claim: 'The city engineer validates the north bridge.',
          source_id: 'synthetic-bridge-001',
          chunk_id: 'missing-chunk',
          score: 0.9,
        },
      ],
      unsupported_claims: [],
      evidence_count: 2,
      insufficient_evidence: false,
    };
    response.writeHead(200, { 'Content-Type': 'application/json' });
    response.end(JSON.stringify({ message: { content: JSON.stringify(answer) } }));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;

  try {
    const result = await runPythonAsync([
      '-m',
      'pdfrejuvenator',
      'answer-query',
      vectorIndex,
      'Who validates the north bridge?',
      '--provider',
      'deterministic-test',
      '--limit',
      '2',
      '--answer-provider',
      'ollama',
      '--answer-model',
      'mock-model',
      '--ollama-url',
      `http://127.0.0.1:${port}`,
      '--output',
      answerPath,
    ]);

    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain('chunk_id does not reference retrieved evidence');
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test('answer-query rejects mock ollama answer overclaim with valid citation', async () => {
  const tempDir = makeTempDir('mock-ollama-overclaim');
  const { vectorIndex } = buildVectorIndex(tempDir);
  const answerPath = path.join(tempDir, 'answer_query.json');

  const server = http.createServer((request, response) => {
    let body = '';
    request.on('data', (chunk) => {
      body += chunk.toString();
    });
    request.on('end', () => {
      const requestPayload = JSON.parse(body);
      const prompt = requestPayload.messages.find((message) => message.role === 'user').content;
      const chunkId = prompt.match(/"chunk_id":"([^"]+)"/)?.[1] || prompt.match(/"chunk_id": "([^"]+)"/)?.[1];
      const sourceId = prompt.match(/"source_id":"([^"]+)"/)?.[1] || prompt.match(/"source_id": "([^"]+)"/)?.[1];
      const answer = {
        schema_version: 'pdfrejuvenator.answer_query.v0.7',
        question: 'Who validates the north bridge?',
        answer: 'The city engineer validates the north bridge and approved the solar treaty.',
        confidence: 'high',
        citations: [
          {
            claim: 'The city engineer validates the north bridge.',
            source_id: sourceId,
            chunk_id: chunkId,
            score: 0.9,
          },
        ],
        unsupported_claims: [],
        evidence_count: 2,
        insufficient_evidence: false,
      };
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ message: { content: JSON.stringify(answer) } }));
    });
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;

  try {
    const result = await runPythonAsync([
      '-m',
      'pdfrejuvenator',
      'answer-query',
      vectorIndex,
      'Who validates the north bridge?',
      '--provider',
      'deterministic-test',
      '--limit',
      '2',
      '--answer-provider',
      'ollama',
      '--answer-model',
      'mock-model',
      '--ollama-url',
      `http://127.0.0.1:${port}`,
      '--output',
      answerPath,
    ]);

    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain('unsupported terms');
    expect(result.stderr).toContain('solar');
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test('answer-query fails closed when mock ollama returns http error', async () => {
  const tempDir = makeTempDir('mock-ollama-http-error');
  const { vectorIndex } = buildVectorIndex(tempDir);
  const answerPath = path.join(tempDir, 'answer_query.json');

  const server = http.createServer((_request, response) => {
    response.writeHead(500, { 'Content-Type': 'application/json' });
    response.end(JSON.stringify({ error: 'forced failure' }));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;

  try {
    const result = await runPythonAsync([
      '-m',
      'pdfrejuvenator',
      'answer-query',
      vectorIndex,
      'Who validates the north bridge?',
      '--provider',
      'deterministic-test',
      '--answer-provider',
      'ollama',
      '--answer-model',
      'mock-model',
      '--ollama-url',
      `http://127.0.0.1:${port}`,
      '--output',
      answerPath,
    ]);

    expect(result.status).toBe(1);
    expect(result.stderr).toContain('ollama answer request failed for model mock-model');
    expect(fs.existsSync(answerPath)).toBe(false);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test('answer-query fails closed when mock ollama times out', async () => {
  const tempDir = makeTempDir('mock-ollama-timeout');
  const { vectorIndex } = buildVectorIndex(tempDir);
  const answerPath = path.join(tempDir, 'answer_query.json');

  const server = http.createServer((_request, _response) => {});
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;

  try {
    const result = await runPythonAsync([
      '-m',
      'pdfrejuvenator',
      'answer-query',
      vectorIndex,
      'Who validates the north bridge?',
      '--provider',
      'deterministic-test',
      '--answer-provider',
      'ollama',
      '--answer-model',
      'mock-model',
      '--answer-timeout-seconds',
      '0.2',
      '--ollama-url',
      `http://127.0.0.1:${port}`,
      '--output',
      answerPath,
    ]);

    expect(result.status).toBe(1);
    expect(result.stderr).toContain('ollama answer request failed for model mock-model');
    expect(fs.existsSync(answerPath)).toBe(false);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test('answer-query rejects generated answers when evidence text is hidden', () => {
  const tempDir = makeTempDir('generated-hidden-evidence');
  const { vectorIndex } = buildVectorIndex(tempDir);
  const answerPath = path.join(tempDir, 'answer_query.json');
  const evidencePath = path.join(tempDir, 'answer_query_evidence.jsonl');

  const result = runPython([
    '-m',
    'pdfrejuvenator',
    'answer-query',
    vectorIndex,
    'Who validates the north bridge?',
    '--provider',
    'deterministic-test',
    '--limit',
    '1',
    '--answer-provider',
    'ollama',
    '--answer-model',
    'mock-model',
    '--hide-evidence-text',
    '--output',
    answerPath,
    '--evidence-output',
    evidencePath,
  ]);

  expect(result.status).toBe(1);
  expect(result.stderr).toContain('generated answers require evidence text');
  expect(fs.existsSync(answerPath)).toBe(false);
  expect(fs.existsSync(evidencePath)).toBe(false);
});
