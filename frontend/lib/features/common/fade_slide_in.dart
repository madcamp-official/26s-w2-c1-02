import 'package:flutter/material.dart';

/// 처음 화면에 나타날 때 한 번, 서서히 나타나며(fade in) 살짝 위로 올라오는(slide up)
/// 위젯. 조건부로 build되는 위젯을 감싸면, 그 위젯이 처음 그려질 때 애니메이션이 재생된다.
class FadeSlideIn extends StatefulWidget {
  const FadeSlideIn({
    super.key,
    required this.child,
    this.duration = const Duration(milliseconds: 420),
    this.beginOffset = 24,
    this.curve = Curves.easeOutCubic,
  });

  final Widget child;
  final Duration duration;

  /// 시작 시 아래로 내려가 있는 픽셀 거리(위로 올라오며 등장).
  final double beginOffset;
  final Curve curve;

  @override
  State<FadeSlideIn> createState() => _FadeSlideInState();
}

class _FadeSlideInState extends State<FadeSlideIn>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller =
      AnimationController(vsync: this, duration: widget.duration);
  late final Animation<double> _t =
      CurvedAnimation(parent: _controller, curve: widget.curve);

  @override
  void initState() {
    super.initState();
    _controller.forward();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _t,
      builder: (context, child) {
        return Opacity(
          opacity: _t.value,
          child: Transform.translate(
            offset: Offset(0, (1 - _t.value) * widget.beginOffset),
            child: child,
          ),
        );
      },
      child: widget.child,
    );
  }
}
