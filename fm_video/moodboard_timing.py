"""Navigation par case : bornes dans le clip et horodatages réels."""
def adjusted_frame(source,frames,selection,slot,anchor,amount):
    position = frames.index(slot)
    lower = selection.get(frames[position-1],frames[position-1])+1 if position else 0
    upper = selection.get(frames[position+1],frames[position+1])-1 if position+1<len(frames) else source.frame_count-1
    lower,upper = max(0,lower),min(source.frame_count-1,upper)
    anchor = max(lower,min(upper,anchor))
    amount = max(-1.,min(1.,amount))
    bound = lower if amount<0 else upper
    time = source.time_of(anchor)+abs(amount)*(source.time_of(bound)-source.time_of(anchor))
    return max(lower,min(upper,int(round(source.index_at_time(time)))))


def timestamp(seconds):
    milliseconds = max(0,round(seconds*1000))
    seconds,milliseconds = divmod(milliseconds,1000)
    minutes,seconds = divmod(seconds,60)
    hours,minutes = divmod(minutes,60)
    return f'{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}'
