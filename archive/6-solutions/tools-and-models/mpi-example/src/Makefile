CC      = mpicc
CFLAGS  = -D_GNU_SOURCE -Wall -Wextra -Werror -g -O2

TARGET  = master_worker

$(TARGET): master_worker.c Makefile
	$(CC) $(CFLAGS) -o $@ master_worker.c

.PHONY: clean
clean:
	rm -f $(TARGET)

.PHONY: debug
debug: CFLAGS += -DDEBUG_MODE
debug: $(TARGET)
