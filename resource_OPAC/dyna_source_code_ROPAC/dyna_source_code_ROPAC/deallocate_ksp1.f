      subroutine deallocate_ksp1
      use muc_mod
      integer error
c --
      deallocate(TTime,stat=error)
      if(error.ne.0)then
        write(911,*) "deallocate TTime error"
        stop
      endif
      deallocate(totalpriority,stat=error)
      if(error.ne.0)then
        write(911,*) "deallocate totalpriority error"
        stop
      endif
      deallocate(Priority,stat=error)
      if(error.ne.0)then
        write(911,*) "deallocate priority error"
        stop
      endif
!	if(iteration .eq. 0) then
      deallocate(pp,stat=error)
      if(error.ne.0)then
        write(911,*) "deallocate pp error"
        stop
      endif
!	endif
! End of modification
	IF(allocated(DequeLabel1))THEN
      deallocate(DequeLabel1,stat=error)
      if(error.ne.0)then
        write(911,*)'deallocate DequeLabel1 error'
        stop
      endif
	ENDIF
      deallocate(DequeLabel2,stat=error)
      if(error.ne.0)then
        write(911,*) "deallocate DequeLabel2 error"
        stop
      endif
      deallocate(DequeLabel1Cost,stat=error)
      if(error.ne.0)then
        write(911,*) "deallocate DequeLabel1Cost error"
        stop
      endif
      deallocate(StatusInDeque,stat=error)
      if(error.ne.0)then
        write(911,*) "deallocate StatusInDeque error"
        stop
      endif
	deallocate(DequeLabelCounter,stat=error)
      if(error.ne.0)then
        write(911,*) "deallocate DequeLabelCounter error"
        stop
      endif
      deallocate(UpCounter,stat=error)
      if(error.ne.0)then
        write(911,*) "deallocate UpCounter error"
        stop
    	endif
      deallocate(Update,stat=error)
      if(error.ne.0)then
        write(911,*) "deallocate Update error"
        stop
      endif
      deallocate(track,stat=error)
      if(error.ne.0)then
        write(911,*) "deallocate track error"
        stop
      endif
      deallocate(ttmarginal,stat=error)
      if(error.ne.0)then
        write(911,*) "deallocate ttmarginal error"
        stop
      endif
	IF(allocated(Label))THEN	
      deallocate(Label,stat=error)
      if(error.ne.0)then
        write(911,*) "deallocate Label error"
        stop
      endif
	ENDIF
c	print *, 'Alex8022'
	IF(allocated(LabelCost))THEN
      deallocate(LabelCost,stat=error)
      if(error.ne.0)then
        write(911,*) "deallocate LabelCost error"
        stop
      endif
	ENDIF
c	print *, 'Alex8023'
	IF(allocated(FirstLabel))THEN
      deallocate(FirstLabel,stat=error)
      if(error.ne.0)then
        write(911,*) "deallocate FirstLabel error"
        stop
      endif
	ENDIF
c	print *, 'Alex8024'
	IF(allocated(LabelPointer))THEN
      deallocate(LabelPointer,stat=error)
      if(error.ne.0)then
        write(911,*) "deallocate LabelPointer error"
        stop
      endif
	ENDIF
c	print *, 'Alex8025'
	IF(allocated(FirstGoodLabel))THEN
      deallocate(FirstGoodLabel,stat=error)
      if(error.ne.0)then
        write(911,*) "deallocate FirstGoodLabel error"
        stop
      endif
	ENDIF
c	print *, 'Alex803'
      deallocate(PathPointer,stat=error)
      if(error.ne.0)then
        write(911,*) "deallocate PathPointer error"
        stop
      endif
c	print *, 'Alex8011-TTpenalty' 
	if(allocated(TTpenalty))then					!Alex: Problem with second dimention, ksptime
          deallocate(TTpenalty,stat=error)
          if(error.ne.0)then
            write(911,*) "deallocate TTpenalty error"
            stop
          endif
	endif
c --
      return
      end
