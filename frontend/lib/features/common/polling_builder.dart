import 'dart:async';

import 'package:flutter/material.dart';

/// 공통 폴링 위젯 (workflow Step 1 · spec §1.2).
///
/// [fetch]를 [interval] 간격으로 반복 호출하고, [isDone]이 true가 되면
/// (예: AsyncStatus.ready | failed) 폴링을 멈춘다. 화면 dispose 시 자동 중단.
///
/// ```dart
/// PollingBuilder<MaterialInfo>(
///   fetch: () => repo.getMaterial(sessionId),
///   isDone: (m) => m.status.isDone,
///   builder: (context, snapshot, retry) { ... },
/// )
/// ```
class PollingBuilder<T> extends StatefulWidget {
  const PollingBuilder({
    super.key,
    required this.fetch,
    required this.isDone,
    required this.builder,
    this.interval = const Duration(milliseconds: 1500),
    this.onDone,
  });

  final Future<T> Function() fetch;
  final bool Function(T data) isDone;

  /// data는 마지막 성공 응답 (첫 응답 전엔 null).
  /// retry는 실패/종료 후 폴링을 처음부터 다시 시작한다.
  final Widget Function(
      BuildContext context, PollingSnapshot<T> snapshot, VoidCallback retry) builder;

  /// spec A2: 1~2초 권장.
  final Duration interval;

  /// isDone 도달 시 1회 호출.
  final void Function(T data)? onDone;

  @override
  State<PollingBuilder<T>> createState() => _PollingBuilderState<T>();
}

class PollingSnapshot<T> {
  const PollingSnapshot({this.data, this.error, required this.polling});

  final T? data;
  final Object? error;

  /// 아직 폴링이 진행 중인지 (완료/에러 시 false).
  final bool polling;

  bool get hasData => data != null;
}

class _PollingBuilderState<T> extends State<PollingBuilder<T>> {
  Timer? _timer;
  T? _data;
  Object? _error;
  bool _polling = true;
  bool _fetching = false;

  @override
  void initState() {
    super.initState();
    _start();
  }

  void _start() {
    _timer?.cancel();
    setState(() {
      _polling = true;
      _error = null;
    });
    _tick(); // 즉시 1회
    _timer = Timer.periodic(widget.interval, (_) => _tick());
  }

  Future<void> _tick() async {
    if (_fetching || !_polling) return; // 응답 지연 시 중첩 호출 방지
    _fetching = true;
    try {
      final data = await widget.fetch();
      if (!mounted) return;
      final done = widget.isDone(data);
      setState(() {
        _data = data;
        _error = null;
        if (done) _polling = false;
      });
      if (done) {
        _timer?.cancel();
        widget.onDone?.call(data);
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e;
        _polling = false; // 네트워크/서버 오류 시 중단 → retry로 재개
      });
      _timer?.cancel();
    } finally {
      _fetching = false;
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return widget.builder(
      context,
      PollingSnapshot(data: _data, error: _error, polling: _polling),
      _start,
    );
  }
}
