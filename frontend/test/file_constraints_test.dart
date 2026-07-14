import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:rehearsal/core/files/file_constraints.dart';

void main() {
  group('발표 자료 검증 (PDF·PPTX · 20MB · 50페이지)', () {
    test('정상 PDF 통과', () {
      final bytes = utf8.encode('%PDF-1.4 /Type /Page x /Type /Page');
      expect(
        FileConstraints.validateMaterial(
            fileName: 'deck.pdf', sizeBytes: bytes.length, bytes: bytes),
        isNull,
      );
    });

    test('정상 PPTX 통과 (대문자 확장자 포함)', () {
      for (final name in ['deck.pptx', 'DECK.PPTX']) {
        expect(
          FileConstraints.validateMaterial(fileName: name, sizeBytes: 1024),
          isNull,
          reason: name,
        );
      }
    });

    test('비허용 확장자 → 거부 (레거시 .ppt 포함)', () {
      for (final name in ['notes.txt', 'deck.ppt', 'deck.key']) {
        expect(
          FileConstraints.validateMaterial(fileName: name, sizeBytes: 100),
          contains('PDF·PPTX'),
          reason: name,
        );
      }
    });

    test('20MB 초과 → 거부 (pdf·pptx 동일)', () {
      for (final name in ['deck.pdf', 'deck.pptx']) {
        expect(
          FileConstraints.validateMaterial(
              fileName: name, sizeBytes: 21 * 1024 * 1024),
          contains('커요'),
          reason: name,
        );
      }
    });

    test('PPTX는 bytes가 있어도 PDF 페이지 추정을 타지 않음', () {
      // PDF 마커가 들어 있는 bytes라도 pptx면 페이지 추정 없이 통과해야 한다.
      final misleading = utf8.encode(List.filled(51, '/Type /Page').join(' '));
      expect(
        FileConstraints.validateMaterial(
            fileName: 'deck.pptx',
            sizeBytes: misleading.length,
            bytes: misleading),
        isNull,
      );
    });

    test('페이지 수 카운트: /Pages(트리 노드)는 세지 않음', () {
      final bytes = utf8.encode(
          '/Type /Pages /Type /Page /Type/Page /Type  /Page /Type /PageLabel');
      // /Page 3개 (/Pages·/PageLabel 제외)
      expect(FileConstraints.estimatePdfPageCount(bytes), 3);
    });

    test('50페이지 초과 → 거부', () {
      final many = List.filled(51, '/Type /Page').join(' ');
      final bytes = utf8.encode('%PDF $many');
      expect(
        FileConstraints.validateMaterial(
            fileName: 'big.pdf', sizeBytes: bytes.length, bytes: bytes),
        contains('페이지'),
      );
    });

    test('페이지 못 세면 null (서버 재검증에 위임)', () {
      expect(FileConstraints.estimatePdfPageCount(utf8.encode('%PDF-1.7')),
          isNull);
    });
  });

  group('오디오 파일 검증 (200MB · mp3/wav/m4a/webm)', () {
    test('허용 확장자 통과', () {
      for (final name in ['a.mp3', 'b.wav', 'c.m4a', 'd.webm', 'E.MP3']) {
        expect(
          FileConstraints.validateAudio(fileName: name, sizeBytes: 1024),
          isNull,
          reason: name,
        );
      }
    });

    test('비허용 확장자 거부', () {
      expect(
        FileConstraints.validateAudio(fileName: 'x.ogg', sizeBytes: 1024),
        isNotNull,
      );
    });

    test('200MB 초과 거부', () {
      expect(
        FileConstraints.validateAudio(
            fileName: 'x.wav', sizeBytes: 201 * 1024 * 1024),
        contains('커요'),
      );
    });
  });
}
