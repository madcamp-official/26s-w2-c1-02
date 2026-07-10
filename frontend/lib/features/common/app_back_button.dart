import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

/// 좌상단 이전(뒤로가기) 버튼.
///
/// 스택에 이전 화면이 있으면 pop, 없으면(=go로 진입해 히스토리가 없을 때)
/// [fallbackLocation]으로 이동한다. AppBar의 leading으로 사용.
class AppBackButton extends StatelessWidget {
  const AppBackButton({super.key, this.fallbackLocation = '/'});

  /// pop할 수 없을 때 이동할 상위 경로.
  final String fallbackLocation;

  @override
  Widget build(BuildContext context) {
    return IconButton(
      tooltip: '이전',
      icon: const Icon(Icons.arrow_back),
      onPressed: () {
        if (context.canPop()) {
          context.pop();
        } else {
          context.go(fallbackLocation);
        }
      },
    );
  }
}
