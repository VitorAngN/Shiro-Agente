import 'dart:collection';

/// Lista com limite (buffer circular): guarda só os últimos [capacity] itens.
///
/// A conversa cresce o dia todo; sem limite, a tela e a memória crescem junto.
/// Inserir é O(1) e descartar o mais antigo também (ListQueue).
class BoundedLog<T> extends IterableBase<T> {
  BoundedLog(this.capacity) : assert(capacity > 0);

  final int capacity;
  final ListQueue<T> _items = ListQueue<T>();

  void add(T item) {
    _items.addLast(item);
    while (_items.length > capacity) {
      _items.removeFirst();
    }
  }

  bool remove(T item) => _items.remove(item);

  T operator [](int index) => _items.elementAt(index);

  @override
  int get length => _items.length;

  @override
  Iterator<T> get iterator => _items.iterator;
}
